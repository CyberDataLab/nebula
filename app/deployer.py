import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import docker
import psutil
from dotenv import load_dotenv
from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer

from nebula.addons.env import check_environment
from nebula.controller.controller import TermEscapeCodeFormatter
from nebula.controller.scenarios import ScenarioManagement
from nebula.utils import DockerUtils, SocketUtils


class NebulaEventHandler(PatternMatchingEventHandler):
    """
    NebulaEventHandler handles file system events for .sh scripts.

    This class monitors the creation, modification, and deletion of .sh scripts
    in a specified directory.
    """

    patterns = ["*.sh", "*.ps1"]

    def __init__(self):
        super().__init__()
        self.last_processed = {}
        self.timeout_ns = 5 * 1e9
        self.processing_files = set()
        self.lock = threading.Lock()

    def _should_process_event(self, src_path: str) -> bool:
        current_time_ns = time.time_ns()
        print(f"Current time (ns): {current_time_ns}")
        with self.lock:
            if src_path in self.last_processed:
                print(f"Last processed time for {src_path}: {self.last_processed[src_path]}")
                last_time = self.last_processed[src_path]
                if current_time_ns - last_time < self.timeout_ns:
                    return False
            self.last_processed[src_path] = current_time_ns
        return True

    def _is_being_processed(self, src_path: str) -> bool:
        with self.lock:
            if src_path in self.processing_files:
                print(f"Skipping {src_path} as it is already being processed.")
                return True
            self.processing_files.add(src_path)
        return False

    def _processing_done(self, src_path: str):
        with self.lock:
            if src_path in self.processing_files:
                self.processing_files.remove(src_path)

    def verify_nodes_ports(self, src_path):
        parent_dir = os.path.dirname(src_path)
        base_dir = os.path.basename(parent_dir)
        scenario_path = os.path.join(os.path.dirname(parent_dir), base_dir)

        try:
            port_mapping = {}
            new_port_start = 50000

            participant_files = sorted(
                f for f in os.listdir(scenario_path) if f.endswith(".json") and f.startswith("participant")
            )

            for filename in participant_files:
                file_path = os.path.join(scenario_path, filename)
                with open(file_path) as json_file:
                    node = json.load(json_file)
                current_port = node["network_args"]["port"]
                port_mapping[current_port] = SocketUtils.find_free_port(start_port=new_port_start)
                print(
                    f"Participant file: {filename} | Current port: {current_port} | New port: {port_mapping[current_port]}"
                )
                new_port_start = port_mapping[current_port] + 1

            for filename in participant_files:
                file_path = os.path.join(scenario_path, filename)
                with open(file_path) as json_file:
                    node = json.load(json_file)
                current_port = node["network_args"]["port"]
                node["network_args"]["port"] = port_mapping[current_port]
                neighbors = node["network_args"]["neighbors"]

                for old_port, new_port in port_mapping.items():
                    neighbors = neighbors.replace(f":{old_port}", f":{new_port}")

                node["network_args"]["neighbors"] = neighbors

                with open(file_path, "w") as f:
                    json.dump(node, f, indent=4)

        except Exception as e:
            print(f"Error processing JSON files: {e}")

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
        print("File created: %s" % src_path)
        try:
            self.verify_nodes_ports(src_path)
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
        print("File deleted: %s" % src_path)
        directory_script = os.path.dirname(src_path)
        pids_file = os.path.join(directory_script, "current_scenario_pids.txt")
        print(f"Killing processes from {pids_file}")
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
            print(f"Running script: {script}")
            if script.endswith(".sh"):
                result = subprocess.run(["bash", script], capture_output=True, text=True)
                print(f"Script output:\n{result.stdout}")
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
                            print(f"Forcibly killing process {pid} and {len(children)} child processes...")
                            for child in children:
                                try:
                                    print(f"Forcibly killing child process {child.pid}")
                                    child.kill()
                                except psutil.NoSuchProcess:
                                    logging.warning(f"Child process {child.pid} already terminated.")
                                except Exception as e:
                                    logging.exception(f"Error while forcibly killing child process {child.pid}: {e}")
                            try:
                                print(f"Forcibly killing main process {pid}")
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


def run_observer():
    # Watchdog for running additional scripts in the host machine (i.e. during the execution of a federation)
    event_handler = NebulaEventHandler()
    observer = Observer()
    config_dir = os.path.join(os.path.dirname(__file__), "/config")
    observer.schedule(event_handler, path=config_dir, recursive=True)
    observer.start()
    observer.join()


class Deployer:
    def __init__(self, args):
        self.controller_port = int(args.controllerport) if hasattr(args, "controllerport") else 5050
        self.waf_port = int(args.wafport) if hasattr(args, "wafport") else 6000
        self.frontend_port = int(args.webport) if hasattr(args, "webport") else 6060
        self.grafana_port = int(args.grafanaport) if hasattr(args, "grafanaport") else 6040
        self.loki_port = int(args.lokiport) if hasattr(args, "lokiport") else 6010
        self.statistics_port = int(args.statsport) if hasattr(args, "statsport") else 8080
        self.production = args.production if hasattr(args, "production") else False
        self.dev = args.developement if hasattr(args, "developement") else False
        self.advanced_analytics = args.advanced_analytics if hasattr(args, "advanced_analytics") else False
        self.databases_dir = args.databases if hasattr(args, "databases") else "/nebula/app/databases"
        self.simulation = args.simulation
        self.config_dir = args.config
        self.log_dir = args.logs
        self.env_path = args.env
        self.root_path = (
            args.root_path
            if hasattr(args, "root_path")
            else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        self.host_platform = "windows" if sys.platform == "win32" else "unix"
        self.controller_host = f"{os.environ['USER']}_nebula-controller"
        self.gpu_available = False
        self.configure_logger()

    def configure_logger(self):
        """
        Configures the logging system for the controller.

        - Sets a format for console and file logging.
        - Creates a console handler with INFO level.
        - Creates a file handler for 'controller.log' with INFO level.
        - Configures specific Uvicorn loggers to use the file handler
          without duplicating log messages.
        """
        log_console_format = "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(TermEscapeCodeFormatter(log_console_format))
        logging.basicConfig(
            level=logging.DEBUG,
            handlers=[
                console_handler,
            ],
        )
        uvicorn_loggers = ["uvicorn", "uvicorn.error", "uvicorn.access"]
        for logger_name in uvicorn_loggers:
            logger = logging.getLogger(logger_name)
            logger.handlers = []  # Remove existing handlers
            logger.propagate = False  # Prevent duplicate logs

    def ensure_directory_access(self, directory_path: str) -> str:
        """
        Ensure the specified directory exists and is writable.

        Args:
            directory_path: Path to the directory to check/create

        Returns:
            str: Absolute path to the directory if successful

        Raises:
            SystemExit: If directory cannot be created or accessed
        """
        try:
            path = Path(os.path.expanduser(directory_path))
            path.mkdir(parents=True, exist_ok=True)

            # Write metadata file to check if directory is writable
            test_file = path / ".metadata"
            try:
                test_file.write_text("nebula")
                test_file.unlink()
            except OSError as e:
                logging.exception(f"Write permission test failed: {str(e)}")
                raise SystemExit(1) from e

            logging.info(f"Successfully verified access to directory: {path}")
            return str(path.absolute())

        except Exception as e:
            logging.exception(f"Failed to create/access directory {directory_path}: {str(e)}")
            logging.exception("Please check directory permissions or choose a different location using --database option")
            raise SystemExit(1) from e

    def start(self):
        banner = """
                    ███╗   ██╗███████╗██████╗ ██╗   ██╗██╗      █████╗
                    ████╗  ██║██╔════╝██╔══██╗██║   ██║██║     ██╔══██╗
                    ██╔██╗ ██║█████╗  ██████╔╝██║   ██║██║     ███████║
                    ██║╚██╗██║██╔══╝  ██╔══██╗██║   ██║██║     ██╔══██║
                    ██║ ╚████║███████╗██████╔╝╚██████╔╝███████╗██║  ██║
                    ╚═╝  ╚═══╝╚══════╝╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝
                      A Platform for Decentralized Federated Learning

                      Developed by:
                       • Enrique Tomás Martínez Beltrán
                       • Alberto Huertas Celdrán
                       • Alejandro Avilés Serrano
                       • Fernando Torres Vega

                      https://nebula-dfl.com / https://nebula-dfl.eu
                """
        print("\x1b[0;36m" + banner + "\x1b[0m")

        # Load the environment variables
        load_dotenv(self.env_path)

        # Check information about the environment
        check_environment()

        # Ensure database directory is accessible
        self.databases_dir = self.ensure_directory_access(self.databases_dir)

        # Save controller pid
        with open(os.path.join(os.path.dirname(__file__), "deployer.pid"), "w") as f:
            f.write(str(os.getpid()))

        # Check ports available
        if not SocketUtils.is_port_open(self.controller_port):
            self.controller_port = SocketUtils.find_free_port(start_port=self.controller_port)

        if not SocketUtils.is_port_open(self.frontend_port):
            self.frontend_port = SocketUtils.find_free_port(start_port=self.frontend_port)

        if not SocketUtils.is_port_open(self.statistics_port):
            self.statistics_port = SocketUtils.find_free_port(start_port=self.statistics_port)

        self.run_controller()
        logging.info("NEBULA Controller is running")
        logging.info(f"NEBULA Databases created in {self.databases_dir}")
        self.run_frontend()
        logging.info(f"NEBULA Frontend is running at http://localhost:{self.frontend_port}")
        if self.production:
            self.run_waf()
            logging.info("NEBULA WAF is running")

        # Watchdog for running additional scripts in the host machine (i.e. during the execution of a federation)
        event_handler = NebulaEventHandler()
        observer = Observer()
        observer.schedule(event_handler, path=self.config_dir, recursive=True)
        observer.start()

        logging.info("Press Ctrl+C for exit from NEBULA (global exit)")

        # Adjust signal handling inside the start method
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGINT, self.signal_handler)

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
            self.stop_all()

    def signal_handler(self, sig, frame):
        """
        Handler for termination signals (SIGTERM, SIGINT).

        - Logs signal reception.
        - Executes a graceful shutdown by calling self.stop().
        - Exits the process with sys.exit(0).

        Parameters:
        - sig: The signal number received.
        - frame: The current stack frame at signal reception.
        """
        logging.info("Received termination signal, shutting down...")
        self.stop_all()
        sys.exit(0)

    def run_frontend(self):
        """
        Starts the NEBULA frontend Docker container.

        - Checks if Docker is running (different checks for Windows and Unix).
        - Detects if an NVIDIA GPU is available and sets a flag.
        - Creates a Docker network named based on the current user.
        - Prepares environment variables and volume mounts for the container.
        - Binds ports for HTTP (80) and statistics (8080).
        - Starts the 'nebula-frontend' container connected to the created network
          with static IP assignment.
        """
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

        try:
            subprocess.check_call(["nvidia-smi"])
            self.gpu_available = True
        except Exception:
            logging.info("No GPU available for the frontend, nodes will be deploy in CPU mode")

        network_name = f"{os.environ['USER']}_nebula-net-base"

        # Create the Docker network
        base = DockerUtils.create_docker_network(network_name)

        client = docker.from_env()

        environment = {
            "NEBULA_CONTROLLER_NAME": os.environ["USER"],
            "NEBULA_PRODUCTION": self.production,
            "NEBULA_GPU_AVAILABLE": self.gpu_available,
            "NEBULA_ADVANCED_ANALYTICS": self.advanced_analytics,
            "NEBULA_FRONTEND_LOG": "/nebula/app/logs/frontend.log",
            "NEBULA_LOGS_DIR": "/nebula/app/logs/",
            "NEBULA_CONFIG_DIR": "/nebula/app/config/",
            "NEBULA_CERTS_DIR": "/nebula/app/certs/",
            "NEBULA_ENV_PATH": "/nebula/app/.env",
            "NEBULA_ROOT_HOST": self.root_path,
            "NEBULA_HOST_PLATFORM": self.host_platform,
            "NEBULA_DEFAULT_USER": "admin",
            "NEBULA_DEFAULT_PASSWORD": "admin",
            "NEBULA_CONTROLLER_PORT": self.controller_port,
            "NEBULA_CONTROLLER_HOST": self.controller_host,
        }

        volumes = ["/nebula", "/var/run/docker.sock", "/etc/nginx/sites-available/default"]

        ports = [80, 8080]

        host_config = client.api.create_host_config(
            binds=[
                f"{self.root_path}:/nebula",
                "/var/run/docker.sock:/var/run/docker.sock",
                f"{self.root_path}/nebula/frontend/config/nebula:/etc/nginx/sites-available/default",
            ],
            port_bindings={80: self.frontend_port, 8080: self.statistics_port},
        )

        networking_config = client.api.create_networking_config({
            f"{network_name}": client.api.create_endpoint_config(ipv4_address=f"{base}.100")
        })

        container_id = client.api.create_container(
            image="nebula-frontend",
            name=f"{os.environ['USER']}_nebula-frontend",
            detach=True,
            environment=environment,
            volumes=volumes,
            host_config=host_config,
            networking_config=networking_config,
            ports=ports,
        )

        client.api.start(container_id)

    @staticmethod
    def stop_frontend():
        """
        Stops all running Docker containers whose names start with
        the pattern '<user>_nebula-frontend'.

        This is used to cleanly shut down the frontend-related containers.
        """
        DockerUtils.remove_containers_by_prefix(f"{os.environ['USER']}_nebula-frontend")

    def run_controller(self):
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

        try:
            subprocess.check_call(["nvidia-smi"])
            self.gpu_available = True
        except Exception:
            logging.info("No GPU available for the frontend, nodes will be deploy in CPU mode")

        network_name = f"{os.environ['USER']}_nebula-net-base"

        # Create the Docker network
        base = DockerUtils.create_docker_network(network_name)

        client = docker.from_env()

        environment = {
            "USER": os.environ["USER"],
            "NEBULA_PRODUCTION": self.production,
            "NEBULA_ROOT_HOST": self.root_path,
            "NEBULA_ADVANCED_ANALYTICS": self.advanced_analytics,
            "NEBULA_DATABASES_DIR": "/nebula/app/databases",
            "NEBULA_CONTROLLER_LOG": "/nebula/app/logs/controller.log",
            "NEBULA_CONFIG_DIR": "/nebula/app/config/",
            "NEBULA_LOGS_DIR": "/nebula/app/logs/",
            "NEBULA_CERTS_DIR": "/nebula/app/certs/",
            "NEBULA_HOST_PLATFORM": self.host_platform,
            "NEBULA_CONTROLLER_PORT": self.controller_port,
            "NEBULA_CONTROLLER_HOST": self.controller_host,
            "NEBULA_FRONTEND_PORT": self.frontend_port,
        }

        volumes = ["/nebula", "/var/run/docker.sock"]

        ports = [self.controller_port]

        host_config = client.api.create_host_config(
            binds=[
                f"{self.root_path}:/nebula",
                "/var/run/docker.sock:/var/run/docker.sock",
                f"{self.databases_dir}:/nebula/app/databases"
            ],
            extra_hosts={"host.docker.internal": "host-gateway"},
            port_bindings={self.controller_port: self.controller_port},
        )

        networking_config = client.api.create_networking_config({
            f"{network_name}": client.api.create_endpoint_config(ipv4_address=f"{base}.150")
        })

        container_id = client.api.create_container(
            image="nebula-controller",
            name=f"{os.environ['USER']}_nebula-controller",
            detach=True,
            environment=environment,
            volumes=volumes,
            host_config=host_config,
            networking_config=networking_config,
            ports=ports,
        )

        client.api.start(container_id)

    @staticmethod
    def stop_controller():
        """
        Stops all running Docker containers whose names start with
        the pattern '<user>_nebula-controller'.

        This is used to cleanly shut down the controller-related containers.
        """
        ScenarioManagement.stop_blockchain()
        ScenarioManagement.stop_participants()
        DockerUtils.remove_containers_by_prefix(f"{os.environ['USER']}_nebula-controller")

    def run_waf(self):
        """
        Starts the Web Application Firewall (WAF) and related monitoring containers.

        - Creates a Docker network named based on the current user.
        - Starts the 'nebula-waf' container with logs volume and port mapping.
        - Starts the 'nebula-waf-grafana' container for monitoring dashboards,
          setting environment variables for Grafana configuration.
        - Starts the 'nebula-waf-loki' container for log aggregation with a config file.
        - Starts the 'nebula-waf-promtail' container to collect logs from nginx.

        All containers are connected to the same Docker network with assigned static IPs.
        """
        network_name = f"{os.environ['USER']}_nebula-net-base"
        base = DockerUtils.create_docker_network(network_name)

        client = docker.from_env()

        volumes_waf = ["/var/log/nginx"]

        ports_waf = [80]

        host_config_waf = client.api.create_host_config(
            binds=[f"{os.environ['NEBULA_LOGS_DIR']}/waf/nginx:/var/log/nginx"],
            privileged=True,
            port_bindings={80: self.waf_port},
        )

        networking_config_waf = client.api.create_networking_config({
            f"{network_name}": client.api.create_endpoint_config(ipv4_address=f"{base}.200")
        })

        container_id_waf = client.api.create_container(
            image="nebula-waf",
            name=f"{os.environ['USER']}_nebula-waf",
            detach=True,
            volumes=volumes_waf,
            host_config=host_config_waf,
            networking_config=networking_config_waf,
            ports=ports_waf,
        )

        client.api.start(container_id_waf)

        environment = {
            "GF_SECURITY_ADMIN_PASSWORD": "admin",
            "GF_USERS_ALLOW_SIGN_UP": "false",
            "GF_SERVER_HTTP_PORT": "3000",
            "GF_SERVER_PROTOCOL": "http",
            "GF_SERVER_DOMAIN": f"localhost:{self.grafana_port}",
            "GF_SERVER_ROOT_URL": f"http://localhost:{self.grafana_port}/grafana/",
            "GF_SERVER_SERVE_FROM_SUB_PATH": "true",
            "GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH": "/var/lib/grafana/dashboards/dashboard.json",
            "GF_METRICS_MAX_LIMIT_TSDB": "0",
        }

        ports = [3000]

        host_config = client.api.create_host_config(
            port_bindings={3000: self.grafana_port},
        )

        networking_config = client.api.create_networking_config({
            f"{network_name}": client.api.create_endpoint_config(ipv4_address=f"{base}.201")
        })

        container_id = client.api.create_container(
            image="nebula-waf-grafana",
            name=f"{os.environ['USER']}_nebula-waf-grafana",
            detach=True,
            environment=environment,
            host_config=host_config,
            networking_config=networking_config,
            ports=ports,
        )

        client.api.start(container_id)

        command = ["-config.file=/mnt/config/loki-config.yml"]

        ports_loki = [3100]

        host_config_loki = client.api.create_host_config(
            port_bindings={3100: self.loki_port},
        )

        networking_config_loki = client.api.create_networking_config({
            f"{network_name}": client.api.create_endpoint_config(ipv4_address=f"{base}.202")
        })

        container_id_loki = client.api.create_container(
            image="nebula-waf-loki",
            name=f"{os.environ['USER']}_nebula-waf-loki",
            detach=True,
            command=command,
            host_config=host_config_loki,
            networking_config=networking_config_loki,
            ports=ports_loki,
        )

        client.api.start(container_id_loki)

        volumes_promtail = ["/var/log/nginx"]

        host_config_promtail = client.api.create_host_config(
            binds=[
                f"{os.environ['NEBULA_LOGS_DIR']}/waf/nginx:/var/log/nginx",
            ],
        )

        networking_config_promtail = client.api.create_networking_config({
            f"{network_name}": client.api.create_endpoint_config(ipv4_address=f"{base}.203")
        })

        container_id_promtail = client.api.create_container(
            image="nebula-waf-promtail",
            name=f"{os.environ['USER']}_nebula-waf-promtail",
            detach=True,
            volumes=volumes_promtail,
            host_config=host_config_promtail,
            networking_config=networking_config_promtail,
        )

        client.api.start(container_id_promtail)

    @staticmethod
    def stop_waf():
        """
        Stops all running Docker containers whose names start with
        the pattern '<user>_nebula-waf'.

        This is used to cleanly shut down the WAF-related containers.
        """
        DockerUtils.remove_containers_by_prefix(f"{os.environ['USER']}_nebula-waf")

    @staticmethod
    def stop_all():
        logging.info("Closing NEBULA (exiting from components)... Please wait")
        try:
            Deployer.stop_frontend()
            Deployer.stop_controller()
            Deployer.stop_waf()
            DockerUtils.remove_containers_by_prefix(f"{os.environ['USER']}_")
            DockerUtils.remove_docker_networks_by_prefix(f"{os.environ['USER']}_")
            deployer_pid_file = os.path.join(os.path.dirname(__file__), "deployer.pid")
            with open(deployer_pid_file) as f:
                pid = int(f.read())
            os.remove(deployer_pid_file)
            os.kill(pid, signal.SIGKILL)
            sys.exit(0)
        except Exception as e:
            logging.info(f"Nebula is closed with errors {e}")
