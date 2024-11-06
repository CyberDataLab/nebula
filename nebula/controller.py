import logging
import os
import re
import signal
import subprocess
import sys
import textwrap
import threading
import time

import psutil
from dotenv import load_dotenv
from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer

from nebula.addons.env import check_environment
from nebula.config.config import Config
from nebula.config.mender import Mender
from nebula.scenarios import ScenarioManagement
from nebula.tests import main as deploy_tests


# Setup controller logger
class TermEscapeCodeFormatter(logging.Formatter):
    def __init__(self, fmt=None, datefmt=None, style="%", validate=True):
        super().__init__(fmt, datefmt, style, validate)

    def format(self, record):
        escape_re = re.compile(r"\x1b\[[0-9;]*m")
        record.msg = re.sub(escape_re, "", str(record.msg))
        return super().format(record)


log_console_format = "[%(levelname)s] - %(asctime)s - Controller - %(message)s"
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
# console_handler.setFormatter(logging.Formatter(log_console_format))
console_handler.setFormatter(TermEscapeCodeFormatter(log_console_format))
logging.basicConfig(
    level=logging.DEBUG,
    handlers=[
        console_handler,
    ],
)


# Detect ctrl+c and run killports
def signal_handler(sig, frame):
    Controller.stop()
    sys.exit(0)


signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


class NebulaEventHandler(PatternMatchingEventHandler):
    """
    NebulaEventHandler handles file system events for .sh scripts.

    This class monitors the creation, modification, and deletion of .sh scripts
    in a specified directory.
    """

    patterns = ["*.sh", "*.ps1"]

    def __init__(self):
        super(NebulaEventHandler, self).__init__()
        self.last_processed = {}
        self.timeout_ns = 5 * 1e9
        self.processing_files = set()
        self.lock = threading.Lock()

    def _should_process_event(self, src_path: str) -> bool:
        current_time_ns = time.time_ns()
        logging.info(f"Current time (ns): {current_time_ns}")
        with self.lock:
            if src_path in self.last_processed:
                logging.info(f"Last processed time for {src_path}: {self.last_processed[src_path]}")
                last_time = self.last_processed[src_path]
                if current_time_ns - last_time < self.timeout_ns:
                    return False
            self.last_processed[src_path] = current_time_ns
        return True

    def _is_being_processed(self, src_path: str) -> bool:
        with self.lock:
            if src_path in self.processing_files:
                logging.info(f"Skipping {src_path} as it is already being processed.")
                return True
            self.processing_files.add(src_path)
        return False

    def _processing_done(self, src_path: str):
        with self.lock:
            if src_path in self.processing_files:
                self.processing_files.remove(src_path)

    def on_created(self, event):
        """
        Handles the event when a file is created.
        """
        if event.is_directory:
            return
        src_path = event.src_path
        if not self._should_process_event(src_path):
            return
        if self._is_being_processed(src_path):
            return
        logging.info("File created: %s" % src_path)
        try:
            self.run_script(src_path)
        finally:
            self._processing_done(src_path)

    def on_deleted(self, event):
        """
        Handles the event when a file is deleted.
        """
        if event.is_directory:
            return
        src_path = event.src_path
        if not self._should_process_event(src_path):
            return
        if self._is_being_processed(src_path):
            return
        logging.info("File deleted: %s" % src_path)
        directory_script = os.path.dirname(src_path)
        pids_file = os.path.join(directory_script, "current_scenario_pids.txt")
        logging.info(f"Killing processes from {pids_file}")
        try:
            self.kill_script_processes(pids_file)
            os.remove(pids_file)
        except FileNotFoundError:
            logging.warning(f"{pids_file} not found.")
        except Exception as e:
            logging.exception(f"Error while killing processes: {e}")
        finally:
            self._processing_done(src_path)

    def run_script(self, script):
        try:
            logging.info(f"Running script: {script}")
            if script.endswith(".sh"):
                result = subprocess.run(["bash", script], capture_output=True, text=True)
                logging.info(f"Script output:\n{result.stdout}")
                if result.stderr:
                    logging.error(f"Script error:\n{result.stderr}")
            elif script.endswith(".ps1"):
                subprocess.Popen(
                    ["powershell", "-ExecutionPolicy", "Bypass", "-File", script],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=False,
                )
            else:
                logging.error("Unsupported script format.")
                return
        except Exception as e:
            logging.exception(f"Error while running script: {e}")

    def kill_script_processes(self, pids_file):
        try:
            with open(pids_file) as f:
                pids = f.readlines()
                for pid in pids:
                    try:
                        pid = int(pid.strip())
                        if psutil.pid_exists(pid):
                            process = psutil.Process(pid)
                            children = process.children(recursive=True)
                            logging.info(f"Forcibly killing process {pid} and {len(children)} child processes...")
                            for child in children:
                                try:
                                    logging.info(f"Forcibly killing child process {child.pid}")
                                    child.kill()
                                except psutil.NoSuchProcess:
                                    logging.warning(f"Child process {child.pid} already terminated.")
                                except Exception as e:
                                    logging.exception(f"Error while forcibly killing child process {child.pid}: {e}")
                            try:
                                logging.info(f"Forcibly killing main process {pid}")
                                process.kill()
                            except psutil.NoSuchProcess:
                                logging.warning(f"Process {pid} already terminated.")
                            except Exception as e:
                                logging.exception(f"Error while forcibly killing main process {pid}: {e}")
                        else:
                            logging.warning(f"PID {pid} does not exist.")
                    except ValueError:
                        logging.exception(f"Invalid PID value in file: {pid}")
                    except Exception as e:
                        logging.exception(f"Error while forcibly killing process {pid}: {e}")
        except FileNotFoundError:
            logging.exception(f"PID file not found: {pids_file}")
        except Exception as e:
            logging.exception(f"Error while reading PIDs from file: {e}")


class Controller:
    def __init__(self, args):
        self.scenario_name = args.scenario_name if hasattr(args, "scenario_name") else None
        self.start_date_scenario = None
        self.federation = args.federation if hasattr(args, "federation") else None
        self.topology = args.topology if hasattr(args, "topology") else None
        self.waf_port = args.wafport if hasattr(args, "wafport") else 6000
        self.frontend_port = args.webport if hasattr(args, "webport") else 6060
        self.grafana_port = args.grafanaport if hasattr(args, "grafanaport") else 6040
        self.loki_port = args.lokiport if hasattr(args, "lokiport") else 6010
        self.statistics_port = args.statsport if hasattr(args, "statsport") else 8080
        self.simulation = args.simulation
        self.config_dir = args.config
        self.test = args.test if hasattr(args, "test") else False
        self.log_dir = args.logs
        self.cert_dir = args.certs
        self.env_path = args.env
        self.production = args.production if hasattr(args, "production") else False
        self.advanced_analytics = args.advanced_analytics if hasattr(args, "advanced_analytics") else False
        self.matrix = args.matrix if hasattr(args, "matrix") else None
        self.root_path = (
            args.root_path
            if hasattr(args, "root_path")
            else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        self.host_platform = "windows" if sys.platform == "win32" else "unix"

        # Network configuration (nodes deployment in a network)
        self.network_subnet = args.network_subnet if hasattr(args, "network_subnet") else None
        self.network_gateway = args.network_gateway if hasattr(args, "network_gateway") else None

        self.config = Config(entity="controller")
        self.topologymanager = None
        self.n_nodes = 0
        self.mender = None if self.simulation else Mender()
        self.use_blockchain = args.use_blockchain if hasattr(args, "use_blockchain") else False
        self.gpu_available = False

    def start(self):
        banner = """
                        ███╗   ██╗███████╗██████╗ ██╗   ██╗██╗      █████╗
                        ████╗  ██║██╔════╝██╔══██╗██║   ██║██║     ██╔══██╗
                        ██╔██╗ ██║█████╗  ██████╔╝██║   ██║██║     ███████║
                        ██║╚██╗██║██╔══╝  ██╔══██╗██║   ██║██║     ██╔══██║
                        ██║ ╚████║███████╗██████╔╝╚██████╔╝███████╗██║  ██║
                        ╚═╝  ╚═══╝╚══════╝╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝
                          A Platform for Decentralized Federated Learning
                            Created by Enrique Tomás Martínez Beltrán
                              https://github.com/CyberDataLab/nebula
                    """
        print("\x1b[0;36m" + banner + "\x1b[0m")

        # Load the environment variables
        load_dotenv(self.env_path)

        # Save controller pid
        with open(os.path.join(os.path.dirname(__file__), "controller.pid"), "w") as f:
            f.write(str(os.getpid()))

        # Check information about the environment
        check_environment()

        # Save the configuration in environment variables
        logging.info("Saving configuration in environment variables...")
        os.environ["NEBULA_ROOT"] = self.root_path
        os.environ["NEBULA_LOGS_DIR"] = self.log_dir
        os.environ["NEBULA_CONFIG_DIR"] = self.config_dir
        os.environ["NEBULA_CERTS_DIR"] = self.cert_dir
        os.environ["NEBULA_STATISTICS_PORT"] = str(self.statistics_port)
        os.environ["NEBULA_ROOT_HOST"] = self.root_path
        os.environ["NEBULA_HOST_PLATFORM"] = self.host_platform

        if self.production:
            self.run_waf()
            logging.info(f"NEBULA WAF is running at port {self.waf_port}")
            logging.info(f"Grafana Dashboard is running at port {self.grafana_port}")

        if self.test:
            self.run_test()
        else:
            self.run_frontend()
            logging.info(f"NEBULA Frontend is running at port {self.frontend_port}")

        # Watchdog for running additional scripts in the host machine (i.e. during the execution of a federation)
        event_handler = NebulaEventHandler()
        observer = Observer()
        observer.schedule(event_handler, path=self.config_dir, recursive=False)
        observer.start()

        if self.mender:
            logging.info("[Mender.module] Mender module initialized")
            time.sleep(2)
            mender = Mender()
            logging.info("[Mender.module] Getting token from Mender server: {}".format(os.getenv("MENDER_SERVER")))
            mender.renew_token()
            time.sleep(2)
            logging.info(
                "[Mender.module] Getting devices from {} with group Cluster_Thun".format(os.getenv("MENDER_SERVER"))
            )
            time.sleep(2)
            devices = mender.get_devices_by_group("Cluster_Thun")
            logging.info("[Mender.module] Getting a pool of devices: 5 devices")
            # devices = devices[:5]
            for i in self.config.participants:
                logging.info(
                    "[Mender.module] Device {} | IP: {}".format(i["device_args"]["idx"], i["network_args"]["ip"])
                )
                logging.info("[Mender.module] \tCreating artifacts...")
                logging.info("[Mender.module] \tSending NEBULA Core...")
                # mender.deploy_artifact_device("my-update-2.0.mender", i['device_args']['idx'])
                logging.info("[Mender.module] \tSending configuration...")
                time.sleep(5)
            sys.exit(0)

        logging.info("Press Ctrl+C for exit from NEBULA (global exit)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Closing NEBULA (exiting from components)... Please wait")
            observer.stop()
            self.stop()

        observer.join()

    def run_waf(self):
        docker_compose_template = textwrap.dedent(
            """
            services:
            {}
        """
        )

        waf_template = textwrap.dedent(
            """
            nebula-waf:
                container_name: nebula-waf
                image: nebula-waf
                build:
                    context: .
                    dockerfile: Dockerfile-waf
                restart: unless-stopped
                volumes:
                    - {log_path}/waf/nginx:/var/log/nginx
                extra_hosts:
                    - "host.docker.internal:host-gateway"
                ipc: host
                privileged: true
                ports:
                    - {waf_port}:80
                networks:
                    nebula-net-base:
                        ipv4_address: {ip}
        """
        )

        grafana_template = textwrap.dedent(
            """
            grafana:
                container_name: nebula-waf-grafana
                image: nebula-waf-grafana
                build:
                    context: .
                    dockerfile: Dockerfile-grafana
                restart: unless-stopped
                environment:
                    - GF_SECURITY_ADMIN_PASSWORD=admin
                    - GF_USERS_ALLOW_SIGN_UP=false
                    - GF_SERVER_HTTP_PORT=3000
                    - GF_SERVER_PROTOCOL=http
                    - GF_SERVER_DOMAIN=localhost:{grafana_port}
                    - GF_SERVER_ROOT_URL=http://localhost:{grafana_port}/grafana/
                    - GF_SERVER_SERVE_FROM_SUB_PATH=true
                    - GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH=/var/lib/grafana/dashboards/dashboard.json
                    - GF_METRICS_MAX_LIMIT_TSDB=0
                ports:
                    - {grafana_port}:3000
                ipc: host
                privileged: true
                networks:
                    nebula-net-base:
                        ipv4_address: {ip}
        """
        )

        loki_template = textwrap.dedent(
            """
            loki:
                container_name: nebula-waf-loki
                image: nebula-waf-loki
                build:
                    context: .
                    dockerfile: Dockerfile-loki
                restart: unless-stopped
                volumes:
                    - ./loki-config.yml:/mnt/config/loki-config.yml
                ports:
                    - {loki_port}:3100
                user: "0:0"
                command:
                    - '-config.file=/mnt/config/loki-config.yml'
                networks:
                    nebula-net-base:
                        ipv4_address: {ip}
        """
        )

        promtail_template = textwrap.dedent(
            """
            promtail:
                container_name: nebula-waf-promtail
                image: nebula-waf-promtail
                build:
                    context: .
                    dockerfile: Dockerfile-promtail
                restart: unless-stopped
                volumes:
                    - {log_path}/waf/nginx:/var/log/nginx
                    - ./promtail-config.yml:/etc/promtail/config.yml
                command:
                    - '-config.file=/etc/promtail/config.yml'
                networks:
                    nebula-net-base:
                        ipv4_address: {ip}
        """
        )

        waf_template = textwrap.indent(waf_template, " " * 4)
        grafana_template = textwrap.indent(grafana_template, " " * 4)
        loki_template = textwrap.indent(loki_template, " " * 4)
        promtail_template = textwrap.indent(promtail_template, " " * 4)

        network_template = textwrap.dedent(
            """
            networks:
                nebula-net-base:
                    name: nebula-net-base
                    driver: bridge
                    ipam:
                        config:
                            - subnet: {}
                              gateway: {}
        """
        )

        # Generate the Docker Compose file dynamically
        services = ""
        services += waf_template.format(
            path=self.root_path,
            log_path=os.environ["NEBULA_LOGS_DIR"],
            waf_port=self.waf_port,
            gw="192.168.10.1",
            ip="192.168.10.200",
        )

        services += grafana_template.format(
            log_path=os.environ["NEBULA_LOGS_DIR"],
            grafana_port=self.grafana_port,
            loki_port=self.loki_port,
            ip="192.168.10.201",
        )

        services += loki_template.format(loki_port=self.loki_port, ip="192.168.10.202")

        services += promtail_template.format(log_path=os.environ["NEBULA_LOGS_DIR"], ip="192.168.10.203")

        docker_compose_file = docker_compose_template.format(services)
        docker_compose_file += network_template.format("192.168.10.0/24", "192.168.10.1")

        # Write the Docker Compose file in waf directory
        with open(
            f"{os.path.join(os.environ['NEBULA_ROOT'], 'nebula', 'addons', 'waf', 'docker-compose.yml')}",
            "w",
        ) as f:
            f.write(docker_compose_file)

        # Start the Docker Compose file, catch error if any
        try:
            subprocess.check_call([
                "docker",
                "compose",
                "-f",
                f"{os.path.join(os.environ['NEBULA_ROOT'], 'nebula', 'addons', 'waf', 'docker-compose.yml')}",
                "up",
                "--build",
                "-d",
            ])
        except subprocess.CalledProcessError:
            raise Exception(
                "Docker Compose failed to start, please check if Docker Compose is installed (https://docs.docker.com/compose/install/) and Docker Engine is running."
            )

    def run_frontend(self):
        if sys.platform == "win32":
            if not os.path.exists("//./pipe/docker_Engine"):
                raise Exception(
                    "Docker is not running, please check if Docker is running and Docker Compose is installed."
                )
        else:
            if not os.path.exists("/var/run/docker.sock"):
                raise Exception(
                    "/var/run/docker.sock not found, please check if Docker is running and Docker Compose is installed."
                )

        docker_compose_template = textwrap.dedent(
            """
            services:
            {}
        """
        )

        frontend_template = textwrap.dedent(
            """
            nebula-frontend:
                container_name: nebula-frontend
                image: nebula-frontend
                build:
                    context: {path}
                    dockerfile: nebula/frontend/Dockerfile
                restart: unless-stopped
                volumes:
                    - {path}:/nebula
                    - /var/run/docker.sock:/var/run/docker.sock
                    - ./config/nebula:/etc/nginx/sites-available/default
                environment:
                    - NEBULA_PRODUCTION={production}
                    - NEBULA_GPU_AVAILABLE={gpu_available}
                    - NEBULA_ADVANCED_ANALYTICS={advanced_analytics}
                    - SERVER_LOG=/nebula/app/logs/server.log
                    - NEBULA_LOGS_DIR=/nebula/app/logs/
                    - NEBULA_CONFIG_DIR=/nebula/app/config/
                    - NEBULA_CORE=/nebula/nebula/core/
                    - NEBULA_CERTS_DIR=/nebula/app/certs/
                    - NEBULA_ENV_PATH=/nebula/app/.env
                    - NEBULA_ROOT_HOST={path}
                    - NEBULA_HOST_PLATFORM={platform}
                    - NEBULA_DEFAULT_USER=admin
                    - NEBULA_DEFAULT_PASSWORD=admin
                    - NEBULA_FRONTEND_PORT={frontend_port}
                extra_hosts:
                    - "host.docker.internal:host-gateway"
                ipc: host
                privileged: true
                ports:
                    - {frontend_port}:80
                    - {statistics_port}:8080
                networks:
                    nebula-net-base:
                        ipv4_address: {ip}
        """
        )
        frontend_template = textwrap.indent(frontend_template, " " * 4)

        network_template = textwrap.dedent(
            """
            networks:
                nebula-net-base:
                    name: nebula-net-base
                    driver: bridge
                    ipam:
                        config:
                            - subnet: {}
                              gateway: {}
        """
        )

        network_template_external = textwrap.dedent(
            """
            networks:
                nebula-net-base:
                    external: true
        """
        )

        try:
            subprocess.check_call(["nvidia-smi"])
            self.gpu_available = True
        except Exception:
            logging.info("No GPU available for the frontend, nodes will be deploy in CPU mode")

        # Generate the Docker Compose file dynamically
        services = ""
        services += frontend_template.format(
            production=self.production,
            gpu_available=self.gpu_available,
            advanced_analytics=self.advanced_analytics,
            path=self.root_path,
            platform=self.host_platform,
            gw="192.168.10.1",
            ip="192.168.10.100",
            frontend_port=self.frontend_port,
            statistics_port=self.statistics_port,
        )
        docker_compose_file = docker_compose_template.format(services)

        if self.production:
            # If WAF is enabled, we need to use the same network
            docker_compose_file += network_template_external
        else:
            docker_compose_file += network_template.format("192.168.10.0/24", "192.168.10.1")
        # Write the Docker Compose file in config directory
        with open(
            f"{os.path.join(os.environ['NEBULA_ROOT'], 'nebula', 'frontend', 'docker-compose.yml')}",
            "w",
        ) as f:
            f.write(docker_compose_file)

        # Start the Docker Compose file, catch error if any
        try:
            subprocess.check_call([
                "docker",
                "compose",
                "-f",
                f"{os.path.join(os.environ['NEBULA_ROOT'], 'nebula', 'frontend', 'docker-compose.yml')}",
                "up",
                "--build",
                "-d",
            ])
        except subprocess.CalledProcessError:
            raise Exception(
                "Docker Compose failed to start, please check if Docker Compose is installed (https://docs.docker.com/compose/install/) and Docker Engine is running."
            )

        except Exception as e:
            raise Exception(f"Error while starting the frontend: {e}")

    def run_test(self):
        deploy_tests.start()

    @staticmethod
    def stop_frontend():
        if sys.platform == "win32":
            try:
                # kill all the docker containers which contain the word "nebula"
                commands = [
                    """docker kill $(docker ps -q --filter ancestor=nebula-frontend) | Out-Null""",
                    """docker rm $(docker ps -a -q --filter ancestor=nebula-frontend) | Out-Null""",
                ]

                for command in commands:
                    time.sleep(1)
                    exit_code = os.system(f'powershell.exe -Command "{command}"')
                    # logging.info(f"Windows Command '{command}' executed with exit code: {exit_code}")

            except Exception as e:
                raise Exception(f"Error while killing docker containers: {e}")
        else:
            try:
                commands = [
                    """docker kill $(docker ps -q --filter ancestor=nebula-frontend) > /dev/null 2>&1""",
                    """docker rm $(docker ps -a -q --filter ancestor=nebula-frontend) > /dev/null 2>&1""",
                ]

                for command in commands:
                    time.sleep(1)
                    exit_code = os.system(command)
                    # logging.info(f"Linux Command '{command}' executed with exit code: {exit_code}")

            except Exception as e:
                raise Exception(f"Error while killing docker containers: {e}")

    @staticmethod
    def stop_network():
        if sys.platform == "win32":
            try:
                # kill all the docker containers which contain the word "nebula"
                commands = [
                    r"""docker network rm $(docker network ls | Where-Object { ($_ -split '\s+')[1] -like 'nebula-net-base' } | ForEach-Object { ($_ -split '\s+')[0] }) | Out-Null"""
                ]

                for command in commands:
                    time.sleep(1)
                    exit_code = os.system(f'powershell.exe -Command "{command}"')
                    # logging.info(f"Windows Command '{command}' executed with exit code: {exit_code}")

            except Exception as e:
                raise Exception(f"Error while killing docker containers: {e}")
        else:
            try:
                commands = [
                    """docker network rm $(docker network ls | grep nebula-net-base | awk '{print $1}') > /dev/null 2>&1"""
                ]

                for command in commands:
                    time.sleep(1)
                    exit_code = os.system(command)
                    # logging.info(f"Linux Command '{command}' executed with exit code: {exit_code}")

            except Exception as e:
                raise Exception(f"Error while killing docker containers: {e}")

    @staticmethod
    def stop_waf():
        if sys.platform == "win32":
            try:
                # kill all the docker containers which contain the word "nebula"
                commands = [
                    """docker compose -p waf down | Out-Null""",
                    """docker compose -p waf rm | Out-Null""",
                ]

                for command in commands:
                    time.sleep(1)
                    exit_code = os.system(f'powershell.exe -Command "{command}"')
                    # logging.info(f"Windows Command '{command}' executed with exit code: {exit_code}")

            except Exception as e:
                raise Exception(f"Error while killing docker containers: {e}")
        else:
            try:
                commands = [
                    """docker compose -p waf down > /dev/null 2>&1""",
                    """docker compose -p waf rm > /dev/null 2>&1""",
                ]

                for command in commands:
                    time.sleep(1)
                    exit_code = os.system(command)
                    # logging.info(f"Linux Command '{command}' executed with exit code: {exit_code}")

            except Exception as e:
                raise Exception(f"Error while killing docker containers: {e}")

    @staticmethod
    def stop():
        logging.info("Closing NEBULA (exiting from components)... Please wait")
        ScenarioManagement.stop_participants()
        ScenarioManagement.stop_blockchain()
        Controller.stop_frontend()
        Controller.stop_waf()
        Controller.stop_network()
        controller_pid_file = os.path.join(os.path.dirname(__file__), "controller.pid")
        try:
            with open(controller_pid_file) as f:
                pid = int(f.read())
                os.kill(pid, signal.SIGKILL)
                os.remove(controller_pid_file)
        except Exception as e:
            logging.exception(f"Error while killing controller process: {e}")
        sys.exit(0)
