import json
import logging
import os
import secrets
import signal
import string
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
from nebula.utils import DockerUtils, FileUtils, SocketUtils

class CredentialManager:
    """
    CredentialManager handles the generation, storage, and validation of environment-based credentials.

    This class is designed to manage credentials required for different system components like the frontend,
    Grafana, and the database. It ensures that secure values are generated and persisted in a `.env` file if
    they are not already defined in the environment.

    Attributes:
        env_path (Path): Absolute path to the environment file where credentials will be stored.

    Typical usage example:
        manager = CredentialManager()
        manager.check_all_credentials()
    """

    def __init__(self, env_dir="app", env_filename=".env"):
        """
        Initializes the CredentialManager and loads existing environment variables from file.

        Args:
            env_dir (str): Directory where the .env file is located. Defaults to 'app'.
            env_filename (str): Name of the environment file. Defaults to '.env'.

        Behavior:
            - Sets up the absolute path to the .env file.
            - Loads any existing environment variables from the file using `load_dotenv`.
        """
        self.env_path = Path.cwd() / env_dir / env_filename
        if os.path.exists(self.env_path):
            logging.info(f"Loading environment variables from {self.env_path}")
            load_dotenv(self.env_path, override=True)

    def generate_secure_password(self, length=20):
        """
        Generates a cryptographically secure and readable password including symbols.

        Args:
            length (int): Length of the password. Defaults to 20.

        Returns:
            str: A randomly generated secure password, excluding confusing or problematic characters.
        """
        alphabet = string.ascii_letters + string.digits + string.punctuation
        for char in ['"', "'", "\\", "`", "|", "(", ")", "{", "}", "[", "]", "#"]:
            alphabet = alphabet.replace(char, "")
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    def check_credential(self, key, is_password=True):
        """
        Checks if a given credential key is present in the environment. If not, generates and saves it.

        Args:
            key (str): The environment variable key to check or create.
            is_password (bool): If True, generates a secure password. If False, generates a hex token. Defaults to True.

        Behavior:
            - If the key is missing, a value is generated and stored both in the environment and the `.env` file.
            - If the key exists, no action is taken.
        """
        if key not in os.environ:
            logging.info(f"Generating value for {key}")
            value = self.generate_secure_password(12) if is_password else secrets.token_hex(24)
            os.environ[key] = value
            logging.info(f"Saving {key} to {self.env_path}")
            with self.env_path.open("a") as f:
                f.write(f"{key}={value}\n")
        else:
            logging.info(f"{key} already set")

    def check_all_credentials(self):
        """
        Checks and sets all required credentials for the application.

        This method should be called at startup to ensure all necessary keys are initialized.

        Includes:
            - Frontend secret key
            - Grafana admin password
            - (Optional) Database password
        """
        self.check_credential("SECRET_KEY", is_password=False)
        self.check_credential("GF_SECURITY_ADMIN_PASSWORD")
        self.check_credential("POSTGRES_PASSWORD")
        self.check_credential("NEBULA_ADMIN_PASSWORD")


class NebulaEventHandler(PatternMatchingEventHandler):
    """
    Handles filesystem events for script files with extensions '.sh' and '.ps1'.

    This class monitors:
        - Creation, modification, and deletion events of shell and PowerShell scripts
          within a specified directory.

    Attributes:
        - patterns: List of file patterns to watch (e.g., '*.sh', '*.ps1').
        - last_processed: Tracks timestamps of last processed events per file to avoid duplicates.
        - timeout_ns: Minimum interval (in nanoseconds) between processing the same file.
        - processing_files: Set of files currently being processed to prevent concurrent handling.
        - lock: Threading lock to synchronize access to shared state during event handling.

    Typical use cases:
        - Automating reactions to script changes such as triggering deployments or validations.
        - Monitoring script directories for dynamic update and execution workflows.
    """

    patterns = ["*.sh", "*.ps1"]

    def __init__(self):
        super().__init__()
        self.last_processed = {}
        self.timeout_ns = 5 * 1e9
        self.processing_files = set()
        self.lock = threading.Lock()

    def _should_process_event(self, src_path: str) -> bool:
        """
        Determines whether a filesystem event for the given file path should be processed.

        This method:
            - Compares the current event timestamp with the last processed timestamp for the file.
            - Uses a timeout threshold to avoid processing duplicate or rapid consecutive events.
            - Ensures thread-safe access to the timestamp records.

        Args:
            src_path (str): The path of the file related to the event.

        Returns:
            bool: True if the event should be processed (not a duplicate within timeout), False otherwise.

        Typical use cases:
            - Debouncing rapid or duplicate filesystem events to prevent redundant processing.
        """
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
        """
        Checks if a file is currently being processed to avoid concurrent handling.

        This method:
            - Uses a thread-safe lock to check and update the set of files under processing.
            - Prevents simultaneous processing of the same file by multiple threads.

        Args:
            src_path (str): The path of the file to check.

        Returns:
            bool: True if the file is already being processed, False otherwise.

        Typical use cases:
            - Ensuring serialized processing of filesystem events for the same file.
        """
        with self.lock:
            if src_path in self.processing_files:
                print(f"Skipping {src_path} as it is already being processed.")
                return True
            self.processing_files.add(src_path)
        return False

    def _processing_done(self, src_path: str):
        """
        Marks the processing of a file as completed, allowing future events for the file to be handled.

        This method:
            - Safely removes the file path from the set of currently processing files.
            - Ensures thread-safe modification of the processing state.

        Args:
            src_path (str): The path of the file whose processing is done.

        Typical use cases:
            - Signaling that a file's event handling is finished to permit subsequent processing.
        """
        with self.lock:
            if src_path in self.processing_files:
                self.processing_files.remove(src_path)

    def verify_nodes_ports(self, src_path):
        """
        Verifies and updates network ports in participant configuration files within a scenario directory.

        This method:
            - Locates participant JSON files in the scenario directory.
            - Maps current ports to new free ports starting from 50000.
            - Updates each participant's port and adjusts their neighbors' port references accordingly.
            - Saves the updated configuration back to the JSON files.
            - Handles and logs any exceptions during processing.

        Args:
            src_path (str): Path to a file within the scenario, used to determine the scenario directory.

        Typical use cases:
            - Avoiding port conflicts by dynamically reassigning ports in distributed federated learning scenarios.
            - Ensuring consistent network configuration across participant nodes.
        """
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
        Handles the creation of a file system event.

        This method:
            - Ignores directory creation events.
            - Debounces rapid or duplicate events using `_should_process_event`.
            - Prevents concurrent processing of the same file via `_is_being_processed`.
            - Logs the creation event.
            - Verifies and updates node ports based on the created file.
            - Executes the created script.
            - Marks processing completion to allow future events for the file.

        Args:
            event: The file system event object containing information about the created file.

        Typical use cases:
            - Reacting to new script files by updating network configurations and executing them automatically.
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
        Handles the deletion of a file system event.

        This method:
            - Ignores directory deletion events.
            - Debounces rapid or duplicate events using `_should_process_event`.
            - Prevents concurrent processing of the same file via `_is_being_processed`.
            - Logs the deletion event.
            - Attempts to kill related processes listed in 'current_scenario_pids.txt' located in the script's directory.
            - Removes the 'current_scenario_pids.txt' file after killing processes.
            - Handles and logs exceptions such as missing PID file or errors during process termination.
            - Marks processing completion to allow future events for the file.

        Args:
            event: The file system event object containing information about the deleted file.

        Typical use cases:
            - Cleaning up running processes when associated script files are removed.
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
        """
        Executes a given script file based on its extension.

        - Runs '.sh' scripts using bash and captures their output and errors.
        - Runs '.ps1' PowerShell scripts with execution policy bypass, launching them asynchronously.
        - Logs an error for unsupported script formats.
        - Catches and logs any exceptions during script execution.

        Args:
            script (str): Path to the script file to be executed.

        Typical use cases:
            - Automatically executing shell or PowerShell scripts triggered by file system events.
        """
        try:
            print(f"Running script: {script}")
            if script.endswith(".sh"):
                result = subprocess.Popen(["bash", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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
        """
        Forcefully terminates processes listed in a given PID file, including their child processes.

        Args:
            pids_file (str): Path to the file containing PIDs, one per line.

        Behavior:
            - Reads the PIDs from the file.
            - For each PID, checks if the process exists.
            - If it exists, kills all child processes recursively before killing the main process.
            - Handles and logs exceptions such as missing processes or invalid PID entries.
            - Logs warnings and errors appropriately.

        Typical use case:
            Used to clean up running processes related to a scenario or script that has been deleted or stopped.
        """
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
    """
    Starts a watchdog observer to monitor the configuration directory for changes.

    This function is typically used to execute additional scripts or trigger events
    during the execution of a federated learning session by monitoring file system changes.

    Main functionalities:
        - Initializes and configures a file system observer.
        - Monitors the `/config` directory for changes.
        - Uses `NebulaEventHandler` to handle detected events.

    Typical use cases:
        - Automatically react to configuration updates.
        - Trigger specific actions during a federation lifecycle.

    Note:
        The observer runs in a blocking mode and will keep the process alive
        until manually stopped or interrupted.
    """
    # Watchdog for running additional scripts in the host machine (i.e. during the execution of a federation)
    event_handler = NebulaEventHandler()
    observer = Observer()
    config_dir = os.path.join(os.path.dirname(__file__), "/config")
    observer.schedule(event_handler, path=config_dir, recursive=True)
    observer.start()
    observer.join()


class Deployer:
    """
    Handles the configuration and initialization of deployment parameters for the NEBULA system.

    This class reads and stores various deployment-related settings such as port assignments,
    environment paths, logging configuration, and system mode (production or development).

    Main functionalities:
        - Parses and validates input arguments for deployment.
        - Sets default values for missing parameters.
        - Detects host platform and sets up environment-specific settings.
        - Initializes the logger for deployment activities.

    Typical use cases:
        - Used to deploy the NEBULA system components with the correct configuration.
        - Enables deployment in different environments (e.g., production, development).

    Attributes:
        - controller_port (int): Port for the main controller service.
        - waf_port (int): Port for the Web Application Firewall (WAF).
        - frontend_port (int): Port for the frontend dashboard.
        - grafana_port (int): Port for Grafana monitoring.
        - loki_port (int): Port for Loki logging service.
        - statistics_port (int): Port for the statistics service.
        - production (bool): Flag indicating if the system is in production mode.
        - dev (bool): Flag indicating if the system is in development mode.
        - databases_dir (str): Path to the database directory.
        - config_dir (str): Path to the configuration directory.
        - log_dir (str): Path to the logs directory.
        - env_path (str): Path to the Python environment.
        - root_path (str): Root directory of the NEBULA system.
        - host_platform (str): Host platform ("windows" or "unix").
        - controller_host (str): Hostname for the controller service.
        - gpu_available (bool): Indicates if a GPU is available on the host.

    Note:
        This class does not launch any services directly; it only prepares and stores configuration.
    """

    DEPLOYER_PID_FILE = os.path.join(os.path.dirname(__file__), "deployer.pid")
    METADATA_FILE = os.path.join(os.path.dirname(__file__), "deployer.metadata")

    @staticmethod
    def _read_metadata():
        try:
            with open(Deployer.METADATA_FILE, "r") as f:
                data = json.load(f)
                # Backward compatibility: if it's a list, treat as containers only
                if isinstance(data, list):
                    return {"containers": data, "networks": []}
                return data
        except (FileNotFoundError, json.JSONDecodeError):
            return {"containers": [], "networks": []}

    @staticmethod
    def _write_metadata(metadata):
        with open(Deployer.METADATA_FILE, "w") as f:
            json.dump(metadata, f, indent=2)

    @staticmethod
    def _add_container_to_metadata(container_name):
        metadata = Deployer._read_metadata()
        if container_name not in metadata["containers"]:
            metadata["containers"].append(container_name)
            Deployer._write_metadata(metadata)

    @staticmethod
    def _add_network_to_metadata(network_name):
        metadata = Deployer._read_metadata()
        if network_name not in metadata["networks"]:
            metadata["networks"].append(network_name)
            Deployer._write_metadata(metadata)

    @staticmethod
    def _remove_all_containers_from_metadata():
        metadata = Deployer._read_metadata()
        containers = metadata["containers"]
        if containers:
            try:
                import docker

                client = docker.from_env()
                for name in containers:
                    try:
                        container = client.containers.get(name)
                        container.remove(force=True)
                        logging.info(f"Container {name} removed via metadata.")
                    except Exception as e:
                        logging.warning(f"Could not remove container {name}: {e}")
            except Exception as e:
                logging.warning(f"Docker error during metadata removal: {e}")
        metadata["containers"] = []
        Deployer._write_metadata(metadata)

    @staticmethod
    def _remove_all_networks_from_metadata():
        metadata = Deployer._read_metadata()
        networks = metadata["networks"]
        if networks:
            try:
                import docker

                client = docker.from_env()
                for name in networks:
                    try:
                        network = client.networks.get(name)
                        network.remove()
                        logging.info(f"Network {name} removed via metadata.")
                    except Exception as e:
                        logging.warning(f"Could not remove network {name}: {e}")
            except Exception as e:
                logging.warning(f"Docker error during network metadata removal: {e}")
        metadata["networks"] = []
        Deployer._write_metadata(metadata)

    def __init__(self, args):
        """
        Initializes the Deployer with robust handling of environment and prefix logic using tags only.
        - Only sets NEBULA_ENV_TAG, NEBULA_PREFIX_TAG, and NEBULA_USER_TAG in the .env file.
        - All logic and naming use tag helpers and tag variables.
        - Defaults for prefix and production are consistent with main.py.
        """
        # Prevent running NEBULA twice by checking metadata file
        if os.path.exists(self.METADATA_FILE):
            try:
                with open(self.METADATA_FILE) as f:
                    data = json.load(f)
                    if (isinstance(data, dict) and (data.get("containers") or data.get("networks"))) or (
                        isinstance(data, list) and data
                    ):
                        warning_msg = (
                            "\n\033[91mERROR: NEBULA appears to be already running or was not cleanly shut down. "
                            "Please stop the existing instance or remove the metadata file before starting a new one.\033[0m\n"
                            "You can use 'docker ps -a --filter name={deployment_prefix}' to see the containers."
                        )
                        logging.exception(warning_msg)
                        sys.exit(1)
            except Exception:
                warning_msg = (
                    "\n\033[91mERROR: NEBULA metadata file is corrupt or unreadable. "
                    "Please remove or fix the file before starting a new instance.\033[0m\n"
                )
                logging.exception(warning_msg)
                sys.exit(1)

        self.configure_logger()
        self.credentialmanager = CredentialManager()
        self.credentialmanager.check_all_credentials()

        # --- Tag logic: CLI args > environment > fallback ---
        arg_production = getattr(args, "production", False)
        arg_prefix = getattr(args, "prefix", "dev")
        arg_user = os.environ.get("USER", "unknown")

        env_tag = os.environ.get("NEBULA_ENV_TAG")
        prefix_tag = os.environ.get("NEBULA_PREFIX_TAG")
        user_tag = os.environ.get("NEBULA_USER_TAG", arg_user)

        self.env_tag = ("prod" if arg_production else "dev") if env_tag is None else env_tag
        self.prefix_tag = arg_prefix if arg_prefix else (prefix_tag if prefix_tag else "dev")
        self.user_tag = user_tag

        FileUtils.update_env_file(getattr(args, "env", ".env"), "NEBULA_ENV_TAG", self.env_tag)
        FileUtils.update_env_file(getattr(args, "env", ".env"), "NEBULA_PREFIX_TAG", self.prefix_tag)
        FileUtils.update_env_file(getattr(args, "env", ".env"), "NEBULA_USER_TAG", self.user_tag)

        self.production = self.env_tag == "prod"
        self.prefix = self.prefix_tag

        deployment_prefix = f"{self.env_tag}_{self.prefix_tag}_{self.user_tag}_"
        if DockerUtils.check_docker_by_prefix(deployment_prefix):
            warning_msg = (
                f"\n\033[91mERROR: Found existing Docker containers with prefix '{deployment_prefix}'. "
                f"NEBULA cannot be deployed with the same prefix. "
                f"Please stop/remove existing containers before starting a new deployment.\033[0m\n"
                f"You can use 'docker ps -a --filter name={deployment_prefix}' to see the containers."
            )
            logging.exception(warning_msg)
            sys.exit(1)

        self.databases_dir = args.databases if hasattr(args, "databases") else "/nebula/app/databases"
        self.config_dir = args.config
        self.log_dir = args.logs
        self.env_path = args.env
        self.root_path = (
            args.root_path
            if hasattr(args, "root_path")
            else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        self.host_platform = "windows" if sys.platform == "win32" else "unix"
        self.gpu_available = False

        self.controller_host = self.get_container_name("nebula-controller")
        self.controller_port = int(args.controllerport) if hasattr(args, "controllerport") else 5050
        self.waf_port = int(args.wafport) if hasattr(args, "wafport") else 6000
        self.frontend_port = int(args.webport) if hasattr(args, "webport") else 6060
        self.grafana_port = int(args.grafanaport) if hasattr(args, "grafanaport") else 6040
        self.loki_port = int(args.lokiport) if hasattr(args, "lokiport") else 6010
        self.statistics_port = int(args.statsport) if hasattr(args, "statsport") else 8080


    def get_container_name(self, role_tag: str) -> str:
        """
        Generate a standardized container name using tags.
        Args:
            role_tag (str): The component role (e.g., 'nebula-controller').
        Returns:
            str: The composed container name.
        """
        return f"{self.env_tag}_{self.prefix_tag}_{self.user_tag}_{role_tag}"

    def get_network_name(self, suffix: str) -> str:
        """
        Generate a standardized network name using tags.
        Args:
            suffix (str): Suffix for the network (default: 'net-base').
        Returns:
            str: The composed network name.
        """
        return f"{self.env_tag}_{self.prefix_tag}_{self.user_tag}_{suffix}"

    @property
    def deployment_prefix(self):
        """
        Returns the deployment prefix for the current deployment.

        This property is used to prefix the names of the containers and networks
        in the deployment.

        Returns:
            str: The deployment prefix, either "production" or "dev".

        Typical use cases:
            - Prefixing container and network names in the deployment.
            - Ensuring consistent naming conventions across different environments.

        """
        return self.prefix

    def configure_logger(self):
        """
        Configures the logging system for the deployment controller.

        This method sets up both console and file logging with a consistent format and appropriate log levels.
        It also ensures that Uvicorn loggers are properly configured to avoid duplicate log outputs.

        Main functionalities:
            - Defines a custom log format.
            - Sets up a stream (console) handler with INFO level.
            - Applies a terminal-specific formatter for better readability.
            - Resets and disables propagation on Uvicorn-related loggers.

        Typical use cases:
            - Enables real-time monitoring of controller events in the console.
            - Ensures clean and consistent logging output during deployment.

        Note:
            This method does not set up file logging directly, but prepares the base configuration
            and Uvicorn logger behavior for further logging use.
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
        Ensures that the specified directory exists and is writable.

        This method attempts to create the directory if it does not exist and verifies
        write access by writing and deleting a temporary metadata file.

        Args:
            directory_path (str): Path to the directory to check or create.

        Returns:
            str: Absolute path to the verified directory.

        Raises:
            SystemExit: If the directory cannot be created or write access is denied.

        Main functionalities:
            - Expands and resolves the given path.
            - Creates the directory if it doesn't exist.
            - Verifies write permissions by writing a temporary file.

        Typical use cases:
            - Validating output paths for logs, databases, or configurations before deployment.
            - Ensuring system compatibility with file permissions in production or development environments.
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
            logging.exception(
                "Please check directory permissions or choose a different location using --database option"
            )
            raise SystemExit(1) from e

    def start(self):
        """
        Starts the NEBULA deployment process and all associated services.

        This method initializes the NEBULA platform by setting up the environment,
        checking port availability, starting key services (controller, frontend, WAF),
        and launching a filesystem observer to react to configuration changes.

        Main functionalities:
            - Displays the NEBULA banner and authorship.
            - Loads environment variables from a file.
            - Verifies environment settings and directory access.
            - Checks and resolves port availability for all components.
            - Starts the controller, frontend, and optionally the WAF.
            - Initializes a watchdog observer to monitor the config directory.
            - Handles system signals for clean shutdown.

        Typical use cases:
            - Used to launch NEBULA in production or development environments.
            - Central entry point for managing NEBULA components during deployment.

        Note:
            The method blocks indefinitely until manually interrupted,
            and ensures graceful shutdown upon receiving SIGINT or SIGTERM.
        """
        banner = f"""
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

                      [{"Production" if self.production else "Development"} mode] [{self.deployment_prefix} prefix]
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
        self.run_database()
        logging.info(f"NEBULA Databases docker is running")
        self.run_frontend()
        logging.info(f"NEBULA Frontend is running at http://localhost:{self.frontend_port}")
        if self.production and self.prefix == "production":
            logging.info("Deploying NEBULA WAF in production mode")
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
        Handles system termination signals to ensure a clean shutdown.

        This method is triggered when the application receives SIGTERM or SIGINT signals
        (e.g., via Ctrl+C or `kill`). It logs the event, performs cleanup actions, and
        terminates the process gracefully.

        Args:
            sig: Signal number received (e.g., signal.SIGINT, signal.SIGTERM).
            frame: Current stack frame at the time the signal was received.

        Main functionalities:
            - Logs the received signal.
            - Calls `self.stop_all()` to terminate running components.
            - Exits the application using `sys.exit(0)`.

        Typical use cases:
            - Ensures that NEBULA services shut down properly on manual or automated termination.
            - Prevents resource leaks or corrupted state during abrupt shutdowns.
        """
        logging.info("Received termination signal, shutting down...")
        self.stop_all()
        sys.exit(0)

    def run_frontend(self):
        """
        Runs the NEBULA controller within a Docker container, ensuring the required Docker environment is available.

        This method:
            - Checks if Docker is running by verifying the Docker socket presence (platform-dependent).
            - Creates a dedicated Docker network for the NEBULA system.
            - Configures environment variables, volume mounts, ports, and network settings for the container.
            - Creates and starts the NEBULA controller Docker container with the specified configuration.

        Raises:
            Exception: If Docker is not running or Docker Compose is not installed.

        Typical use cases:
            - Launching the NEBULA controller as part of the federated learning infrastructure.
            - Ensuring proper Docker networking and environment setup for container execution.

        Note:
            This method assumes Docker and Docker Compose are installed and accessible on the host system.
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

        network_name = self.get_network_name("net-base")

        # Create the Docker network
        base = DockerUtils.create_docker_network(network_name)
        Deployer._add_network_to_metadata(network_name)

        client = docker.from_env()

        environment = {
            "SECRET_KEY": os.environ.get("SECRET_KEY"),
            "NEBULA_PRODUCTION": self.production,
            "NEBULA_ENV_TAG": self.env_tag,
            "NEBULA_PREFIX_TAG": self.prefix_tag,
            "NEBULA_USER_TAG": self.user_tag,
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

        frontend_container_name = self.get_container_name("nebula-frontend")

        try:
            existing = client.containers.get(frontend_container_name)
            logging.warning(
                f"Container {frontend_container_name} already exists. Deployment may fail or cause conflicts."
            )
        except docker.errors.NotFound:
            pass  # No conflict, safe to proceed

        container_id = client.api.create_container(
            image="nebula-frontend",
            name=frontend_container_name,
            detach=True,
            environment=environment,
            volumes=volumes,
            host_config=host_config,
            networking_config=networking_config,
            ports=ports,
        )

        client.api.start(container_id)
        # Add to metadata
        Deployer._add_container_to_metadata(frontend_container_name)

    def run_database(self):
        """
        Runs the Nebula database within a Docker container, ensuring the required Docker environment is available.
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

        network_name = self.get_network_name("net-base")
        base = DockerUtils.create_docker_network(network_name)
        Deployer._add_network_to_metadata(network_name)

        client = docker.from_env()

        # --- PostgreSQL ---
        pg_container_name = self.get_container_name("nebula-database")
        pg_environment = {
            "POSTGRES_USER": "nebula",
            "POSTGRES_PASSWORD": os.environ.get("POSTGRES_PASSWORD"),
            "POSTGRES_DB": "nebula",
        }
        host_sql_path = os.path.join(self.root_path, "nebula/database/init-configs.sql")
        db_data_path = os.path.join(self.databases_dir, "postgres-data")
        os.makedirs(db_data_path, exist_ok=True)

        pg_host_config = client.api.create_host_config(
            binds=[
                f"{host_sql_path}:/docker-entrypoint-initdb.d/init-configs.sql",
                f"{db_data_path}:/var/lib/postgresql/data",
            ],
            port_bindings={5432: 5432},
        )
        pg_networking_config = client.api.create_networking_config(
            {f"{network_name}": client.api.create_endpoint_config(ipv4_address=f"{base}.125")}
        )

        pg_container = client.api.create_container(
            image="nebula-database",
            name=pg_container_name,
            detach=True,
            environment=pg_environment,
            host_config=pg_host_config,
            networking_config=pg_networking_config,
        )
        client.api.start(pg_container)
        Deployer._add_container_to_metadata(pg_container_name)

        # --- PGWeb ---
        pgweb_container_name = self.get_container_name("nebula-pgweb")
        pgweb_host_config = client.api.create_host_config(port_bindings={8081: 8085})
        pgweb_networking_config = client.api.create_networking_config(
            {f"{network_name}": client.api.create_endpoint_config(ipv4_address=f"{base}.135")}
        )

        pgweb_container = client.api.create_container(
            image="nebula-pgweb",
            name=pgweb_container_name,
            detach=True,
            host_config=pgweb_host_config,
            networking_config=pgweb_networking_config,
        )
        client.api.start(pgweb_container)
        Deployer._add_container_to_metadata(pgweb_container_name)

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

        network_name = self.get_network_name("net-base")

        try:
            subprocess.check_call(["nvidia-smi"])
            self.gpu_available = True
        except Exception:
            logging.info("No GPU available for the frontend, nodes will be deploy in CPU mode")

        # Create the Docker network
        base = DockerUtils.create_docker_network(network_name)
        Deployer._add_network_to_metadata(network_name)

        client = docker.from_env()

        environment = {
            "USER": os.environ["USER"],
            "NEBULA_ENV_TAG": self.env_tag,
            "NEBULA_PREFIX_TAG": self.prefix_tag,
            "NEBULA_USER_TAG": self.user_tag,
            "NEBULA_ROOT_HOST": self.root_path,
            "NEBULA_DATABASES_DIR": "/nebula/app/databases",
            "NEBULA_CONTROLLER_LOG": "/nebula/app/logs/controller.log",
            "NEBULA_CONFIG_DIR": "/nebula/app/config/",
            "NEBULA_LOGS_DIR": "/nebula/app/logs/",
            "NEBULA_CERTS_DIR": "/nebula/app/certs/",
            "NEBULA_HOST_PLATFORM": self.host_platform,
            "NEBULA_CONTROLLER_PORT": self.controller_port,
            "NEBULA_CONTROLLER_HOST": self.controller_host,
            "NEBULA_FRONTEND_PORT": self.frontend_port,
            "DB_HOST": self.get_container_name("nebula-database"),
            "DB_PORT": 5432,
            "DB_USER": "nebula",
            "DB_PASSWORD": os.environ.get("POSTGRES_PASSWORD"),
            "NEBULA_ADMIN_PASSWORD": os.environ.get("NEBULA_ADMIN_PASSWORD")
        }

        volumes = ["/nebula", "/var/run/docker.sock"]

        ports = [self.controller_port]

        host_config = client.api.create_host_config(
            binds=[
                f"{self.root_path}:/nebula",
                "/var/run/docker.sock:/var/run/docker.sock",
                f"{self.databases_dir}:/nebula/app/databases",
            ],
            extra_hosts={"host.docker.internal": "host-gateway"},
            port_bindings={self.controller_port: self.controller_port},
            device_requests=[
                {
                    "Driver": "nvidia",
                    "Count": -1,
                    "Capabilities": [["gpu"]],
                }
            ]
            if self.gpu_available
            else None,
        )

        networking_config = client.api.create_networking_config({
            f"{network_name}": client.api.create_endpoint_config(ipv4_address=f"{base}.150")
        })

        controller_container_name = self.get_container_name("nebula-controller")

        try:
            existing = client.containers.get(controller_container_name)
            logging.warning(
                f"Container {controller_container_name} already exists. Deployment may fail or cause conflicts."
            )
        except docker.errors.NotFound:
            pass  # No conflict, safe to proceed

        container_id = client.api.create_container(
            image="nebula-controller",
            name=controller_container_name,
            detach=True,
            environment=environment,
            volumes=volumes,
            host_config=host_config,
            networking_config=networking_config,
            ports=ports,
        )

        client.api.start(container_id)
        # Add to metadata
        Deployer._add_container_to_metadata(controller_container_name)

    def run_waf(self):
        """
        Starts and configures the Web Application Firewall (WAF) and its monitoring stack within Docker containers.

        This method:
            - Creates a user-specific Docker network for WAF-related containers.
            - Launches the 'nebula-waf' container to provide WAF functionality with log volume and port mappings.
            - Starts the 'nebula-waf-grafana' container for monitoring dashboards, configured via environment variables.
            - Launches the 'nebula-waf-loki' container for centralized log aggregation using a configuration file.
            - Starts the 'nebula-waf-promtail' container to collect and forward logs from nginx.
            - Assigns static IP addresses to all containers within the created Docker network for consistent communication.

        Typical use cases:
            - Deploying an integrated WAF solution alongside monitoring and logging components in the NEBULA system.
            - Ensuring comprehensive security monitoring and log management through containerized services.
        """
        network_name = self.get_network_name("net-base")
        base = DockerUtils.create_docker_network(network_name)
        Deployer._add_network_to_metadata(network_name)

        client = docker.from_env()

        volumes_waf = ["/var/log/nginx"]

        ports_waf = [80]

        host_config_waf = client.api.create_host_config(
            binds=[f"{self.log_dir}/waf/nginx:/var/log/nginx"],
            privileged=True,
            port_bindings={80: self.waf_port},
        )

        networking_config_waf = client.api.create_networking_config({
            f"{network_name}": client.api.create_endpoint_config(ipv4_address=f"{base}.200")
        })

        waf_container_name = self.get_container_name("nebula-waf")

        try:
            existing = client.containers.get(waf_container_name)
            logging.warning(f"Container {waf_container_name} already exists. Deployment may fail or cause conflicts.")
        except docker.errors.NotFound:
            pass  # No conflict, safe to proceed

        container_id_waf = client.api.create_container(
            image="nebula-waf",
            name=waf_container_name,
            detach=True,
            volumes=volumes_waf,
            host_config=host_config_waf,
            networking_config=networking_config_waf,
            ports=ports_waf,
        )

        client.api.start(container_id_waf)
        Deployer._add_container_to_metadata(waf_container_name)

        environment = {
            "GF_SECURITY_ADMIN_PASSWORD": os.environ.get("GF_SECURITY_ADMIN_PASSWORD"),
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

        waf_grafana_container_name = self.get_container_name("nebula-waf-grafana")

        try:
            existing = client.containers.get(waf_grafana_container_name)
            logging.warning(
                f"Container {waf_grafana_container_name} already exists. Deployment may fail or cause conflicts."
            )
        except docker.errors.NotFound:
            pass  # No conflict, safe to proceed

        container_id = client.api.create_container(
            image="nebula-waf-grafana",
            name=waf_grafana_container_name,
            detach=True,
            environment=environment,
            host_config=host_config,
            networking_config=networking_config,
            ports=ports,
        )

        client.api.start(container_id)
        Deployer._add_container_to_metadata(waf_grafana_container_name)

        command = ["-config.file=/mnt/config/loki-config.yml"]

        ports_loki = [3100]

        host_config_loki = client.api.create_host_config(
            port_bindings={3100: self.loki_port},
        )

        networking_config_loki = client.api.create_networking_config({
            f"{network_name}": client.api.create_endpoint_config(ipv4_address=f"{base}.202")
        })

        waf_loki_container_name = self.get_container_name("nebula-waf-loki")

        try:
            existing = client.containers.get(waf_loki_container_name)
            logging.warning(
                f"Container {waf_loki_container_name} already exists. Deployment may fail or cause conflicts."
            )
        except docker.errors.NotFound:
            pass  # No conflict, safe to proceed

        container_id_loki = client.api.create_container(
            image="nebula-waf-loki",
            name=waf_loki_container_name,
            detach=True,
            command=command,
            host_config=host_config_loki,
            networking_config=networking_config_loki,
            ports=ports_loki,
        )

        client.api.start(container_id_loki)
        Deployer._add_container_to_metadata(waf_loki_container_name)

        volumes_promtail = ["/var/log/nginx"]

        host_config_promtail = client.api.create_host_config(
            binds=[
                f"{self.log_dir}/waf/nginx:/var/log/nginx",
            ],
        )

        networking_config_promtail = client.api.create_networking_config({
            f"{network_name}": client.api.create_endpoint_config(ipv4_address=f"{base}.203")
        })

        waf_promtail_container_name = self.get_container_name("nebula-waf-promtail")

        try:
            existing = client.containers.get(waf_promtail_container_name)
            logging.warning(
                f"Container {waf_promtail_container_name} already exists. Deployment may fail or cause conflicts."
            )
        except docker.errors.NotFound:
            pass  # No conflict, safe to proceed

        container_id_promtail = client.api.create_container(
            image="nebula-waf-promtail",
            name=waf_promtail_container_name,
            detach=True,
            volumes=volumes_promtail,
            host_config=host_config_promtail,
            networking_config=networking_config_promtail,
        )

        client.api.start(container_id_promtail)
        Deployer._add_container_to_metadata(waf_promtail_container_name)

    @staticmethod
    def stop_deployer():
        if os.path.exists(Deployer.DEPLOYER_PID_FILE):
            try:
                with open(Deployer.DEPLOYER_PID_FILE) as f:
                    pid = int(f.read())
                os.remove(Deployer.DEPLOYER_PID_FILE)
                # Check if process still exists before trying to kill it
                if psutil.pid_exists(pid):
                    os.kill(pid, signal.SIGKILL)
                    logging.info(f"Deployer process {pid} terminated")
                else:
                    logging.info(f"Deployer process {pid} already terminated")
            except (ValueError, OSError) as e:
                logging.warning(f"Error stopping deployer process: {e}")
            except Exception as e:
                logging.warning(f"Unexpected error stopping deployer process: {e}")

    @staticmethod
    def stop_all():
        """
        Stops all running NEBULA-related Docker containers and networks, then terminates the deployer process.

        Responsibilities:
            - Stops frontend, controller, and WAF containers for the current user.
            - Removes all Docker containers tracked in the metadata file.
            - Reads and kills the deployer process using its PID file.
            - Exits the system cleanly, handling any exceptions during shutdown.

        Typical use cases:
            - Full shutdown and cleanup of all NEBULA components and resources on the host system.
        """
        print("Closing NEBULA (exiting from components)... Please wait")
        errors = []

        try:
            # Remove all scenario containers
            ScenarioManagement.cleanup_scenario_containers()
        except Exception as e:
            errors.append(f"Scenario cleanup error: {e}")
            logging.warning(f"Error during scenario cleanup: {e}")

        try:
            Deployer._remove_all_containers_from_metadata()
        except Exception as e:
            errors.append(f"Container cleanup error: {e}")
            logging.warning(f"Error during container cleanup: {e}")

        try:
            Deployer._remove_all_networks_from_metadata()
        except Exception as e:
            errors.append(f"Network cleanup error: {e}")
            logging.warning(f"Error during network cleanup: {e}")

        try:
            # Remove the metadata file after cleanup
            if os.path.exists(Deployer.METADATA_FILE):
                os.remove(Deployer.METADATA_FILE)
        except Exception as e:
            errors.append(f"Metadata file removal error: {e}")
            logging.warning(f"Error removing metadata file: {e}")

        try:
            Deployer.stop_deployer()
        except Exception as e:
            errors.append(f"Deployer stop error: {e}")
            logging.warning(f"Error stopping deployer: {e}")

        if errors:
            print(f"NEBULA is closed with errors: {'; '.join(errors)}")
        else:
            print("NEBULA closed successfully")

        sys.exit(0)
