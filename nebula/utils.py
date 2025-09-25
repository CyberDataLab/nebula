import logging
import os
import socket

import aiohttp
import aiohttp
import docker

import re
from typing import Optional

from fastapi import HTTPException
from aiohttp import ClientConnectorError
from aiohttp.client_exceptions import ClientError
import asyncio
import re
from typing import Optional

from fastapi import HTTPException
from aiohttp import ClientConnectorError
from aiohttp.client_exceptions import ClientError
import asyncio

class FileUtils:
    """
    Utility class for file operations.
    """

    @classmethod
    def check_path(cls, base_path, relative_path):
        """
        Joins and normalizes a base path with a relative path, then validates
        that the resulting full path is inside the base path directory.

        Args:
            base_path (str): The base directory path.
            relative_path (str): The relative path to join with the base path.

        Returns:
            str: The normalized full path.

        Raises:
            Exception: If the resulting path is outside the base directory.
        """
        full_path = os.path.normpath(os.path.join(base_path, relative_path))
        base_path = os.path.normpath(base_path)

        if not full_path.startswith(base_path):
            raise Exception("Not allowed")
        return full_path

    @classmethod
    def update_env_file(cls, env_file, key, value):
        """
        Update or add a key-value pair in the .env file.
        """
        import re
        lines = []
        if os.path.exists(env_file):
            with open(env_file, "r") as f:
                lines = f.readlines()
        key_found = False
        for i, line in enumerate(lines):
            if re.match(rf"^{key}=.*", line):
                lines[i] = f"{key}={value}\n"
                key_found = True
                break
        if not key_found:
            lines.append(f"{key}={value}\n")
        with open(env_file, "w") as f:
            f.writelines(lines)


class SocketUtils:
    """
    Utility class for socket operations.
    """

    @classmethod
    def is_port_open(cls, port):
        """
        Checks if a TCP port is available (not currently bound) on localhost.

        Args:
            port (int): The port number to check.

        Returns:
            bool: True if the port is free (available), False if it is in use.
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            s.close()
            return True
        except OSError:
            return False

    @classmethod
    def find_free_port(cls, start_port=49152, end_port=65535):
        """
        Finds and returns the first available TCP port within the specified range.

        Args:
            start_port (int, optional): Starting port number to check. Defaults to 49152.
            end_port (int, optional): Ending port number to check. Defaults to 65535.

        Returns:
            int or None: The first free port found, or None if no free port is found.
        """
        for port in range(start_port, end_port + 1):
            if cls.is_port_open(port):
                return port
        return None

class DockerUtils:
    """
    Utility class for Docker operations such as creating networks,
    checking containers, and removing networks or containers by name prefix.
    """

    @classmethod
    def create_docker_network(cls, network_name, subnet=None, prefix=24):
        """
        Creates a Docker bridge network with a given name and optional subnet.
        If subnet is None or already in use, it finds an available subnet in
        the 192.168.X.0/24 range starting from 192.168.50.0/24.

        Args:
            network_name (str): Name of the Docker network to create.
            subnet (str, optional): Subnet in CIDR notation (e.g. "192.168.50.0/24").
            prefix (int, optional): Network prefix length, default is 24.

        Returns:
            str or None: The base subnet (e.g. "192.168.50") of the created or existing
                         network, or None if an error occurred.
        """
        try:
            # Connect to Docker
            client = docker.from_env()
            base_subnet = "192.168"

            # Obtain existing docker subnets
            existing_subnets = []
            networks = client.networks.list()

            existing_network = next((n for n in networks if n.name == network_name), None)

            if existing_network:
                ipam_config = existing_network.attrs.get("IPAM", {}).get("Config", [])
                if ipam_config:
                    # Assume there's only one subnet per network for simplicity
                    existing_subnet = ipam_config[0].get("Subnet", "")
                    potential_base = ".".join(existing_subnet.split(".")[:3])  # Extract base from subnet
                    logging.info(f"Network '{network_name}' already exists with base {potential_base}")
                    return potential_base

            for network in networks:
                ipam_config = network.attrs.get("IPAM", {}).get("Config", [])
                if ipam_config:
                    for config in ipam_config:
                        if "Subnet" in config:
                            existing_subnets.append(config["Subnet"])

            # If no subnet is provided or it exists, find the next available one
            if not subnet or subnet in existing_subnets:
                for i in range(50, 255):  # Iterate over 192.168.50.0 to 192.168.254.0
                    subnet = f"{base_subnet}.{i}.0/{prefix}"
                    potential_base = f"{base_subnet}.{i}"
                    if subnet not in existing_subnets:
                        break
                else:
                    raise ValueError("No available subnets found.")

            # Create the Docker network
            gateway = f"{subnet.split('/')[0].rsplit('.', 1)[0]}.1"
            ipam_pool = docker.types.IPAMPool(subnet=subnet, gateway=gateway)
            ipam_config = docker.types.IPAMConfig(pool_configs=[ipam_pool])
            network = client.networks.create(name=network_name, driver="bridge", ipam=ipam_config)

            logging.info(f"Network created: {network.name} with subnet {subnet}")
            return potential_base

        except docker.errors.APIError:
            logging.exception("Error interacting with Docker")
            return None
        except Exception:
            logging.exception("Unexpected error")
            return None
        finally:
            client.close()  # Ensure the Docker client is closed

    @classmethod
    def check_docker_by_prefix(cls, prefix):
        """
        Checks if there are any Docker containers whose names start with the given prefix.

        Args:
            prefix (str): Prefix string to match container names.

        Returns:
            bool: True if any container matches the prefix, False otherwise.
        """
        try:
            # Connect to Docker client
            client = docker.from_env()

            containers = client.containers.list(all=True)  # `all=True` to include stopped containers

            # Iterate through containers and remove those with the matching prefix
            for container in containers:
                if container.name.startswith(prefix):
                    return True

            return False

        except docker.errors.APIError:
            logging.exception("Error interacting with Docker")
        except Exception:
            logging.exception("Unexpected error")

class HashUtils:

    @staticmethod
    def generate_md5(value: str) -> str:
        import hashlib
        return hashlib.md5(value.encode("utf-8")).hexdigest()

    @staticmethod
    def generate_sha256(value: str) -> str:
        import hashlib
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

# Setup controller logger
class TermEscapeCodeFormatter(logging.Formatter):
    """
    Custom logging formatter that removes ANSI terminal escape codes from log messages.

    This formatter is useful when you want to clean up log outputs by stripping out
    any terminal color codes or formatting sequences before logging them to a file
    or other non-terminal output.

    Attributes:
        fmt (str): Format string for the log message.
        datefmt (str): Format string for the date in the log message.
        style (str): Formatting style (default is '%').
        validate (bool): Whether to validate the format string.

    Methods:
        format(record): Strips ANSI escape codes from the log message and formats it.
    """

    def __init__(self, fmt=None, datefmt=None, style="%", validate=True):
        """
        Initializes the TermEscapeCodeFormatter.

        Args:
            fmt (str, optional): The format string for the log message.
            datefmt (str, optional): The format string for the date.
            style (str, optional): The formatting style. Defaults to '%'.
            validate (bool, optional): Whether to validate the format string. Defaults to True.
        """
        super().__init__(fmt, datefmt, style, validate)

    def format(self, record):
        """
        Formats the specified log record, stripping out any ANSI escape codes.

        Args:
            record (logging.LogRecord): The log record to be formatted.

        Returns:
            str: The formatted log message with escape codes removed.
        """
        escape_re = re.compile(r"\x1b\[[0-9;]*m")
        record.msg = re.sub(escape_re, "", str(record.msg))
        return super().format(record)

    @staticmethod
    def configure_logger(controller_log):
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
        console_handler_file = logging.FileHandler(os.path.join(controller_log), mode="w")
        console_handler_file.setLevel(logging.INFO)
        console_handler_file.setFormatter(logging.Formatter("[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"))
        logging.basicConfig(
            level=logging.DEBUG,
            handlers=[
                console_handler,
                console_handler_file,
            ],
        )
        uvicorn_loggers = ["uvicorn", "uvicorn.error", "uvicorn.access"]
        for logger_name in uvicorn_loggers:
            logger = logging.getLogger(logger_name)
            logger.handlers = []  # Remove existing handlers
            logger.propagate = False  # Prevent duplicate logs
            handler = logging.FileHandler(os.path.join(controller_log), mode="a")
            handler.setFormatter(logging.Formatter("[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"))
            logger.addHandler(handler)


class LoggerUtils:

    @staticmethod
    def configure_logger(
        name: Optional[str] = None,
        log_file: Optional[str] = None,
        level: int = logging.INFO,
        console: bool = True,
        strip_ansi: bool = True,
        file_mode: str = "w",
        log_format: str = "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
        date_format: str = "%Y-%m-%d %H:%M:%S",
    ) -> logging.Logger:
        """
        Configure and return a logger with optional console and file output.

        Args:
            name (str): Logger name. If None, the root logger is used.
            log_file (str): Path to the log file.
            level (int): Logging level (DEBUG, INFO, etc).
            console (bool): If True, output is also printed to the console.
            strip_ansi (bool): Placeholder for future ANSI stripping support.
            file_mode (str): File mode for the log file ('a' for append, 'w' for overwrite).
            log_format (str): Format for log messages.
            date_format (str): Format for timestamps.

        Returns:
            logging.Logger: Configured logger instance.
        """
        logger = logging.getLogger(name)
        logger.setLevel(level)

        # Prevent duplicate handler setup
        if getattr(logger, "_is_configured", False):
            return logger

        formatter = logging.Formatter(fmt=log_format, datefmt=date_format)

        if log_file:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            fh = logging.FileHandler(log_file, mode=file_mode)
            fh.setLevel(level)
            fh.setFormatter(formatter)
            logger.addHandler(fh)

        if console:
            ch = logging.StreamHandler()
            ch.setLevel(level)
            ch.setFormatter(formatter)
            logger.addHandler(ch)

        # Mark this logger as configured to avoid re-adding handlers
        logger._is_configured = True
        logger.propagate = False

        return logger

class APIUtils():

    @staticmethod
    async def retry_with_backoff(func, *args, max_retries=5, initial_delay=1):
        """
        Retry a function with exponential backoff.

        Args:
            func: The async function to retry
            *args: Arguments to pass to the function
            max_retries: Maximum number of retry attempts
            initial_delay: Initial delay between retries in seconds

        Returns:
            The result of the function if successful

        Raises:
            The last exception if all retries fail
        """
        delay = initial_delay
        last_exception = None

        for attempt in range(max_retries):
            try:
                return await func(*args)
            except (ClientConnectorError, ClientError) as e:
                last_exception = e
                if attempt < max_retries - 1:
                    logging.warning(f"Connection attempt {attempt + 1} failed: {str(e)}. Retrying in {delay} seconds...")
                    await asyncio.sleep(delay)
                    delay *= 2  # Exponential backoff
                else:
                    logging.error(f"All {max_retries} connection attempts failed")
                    raise last_exception

    @staticmethod
    async def get(url, params=None):
        """
        Fetch JSON data from a remote controller endpoint via asynchronous HTTP GET.

        Parameters:
            url (str): The full URL of the controller API endpoint.
            params (dict, optional): A dictionary of query parameters to be sent with the request.

        Returns:
            Any: Parsed JSON response when the HTTP status code is 200.

        Raises:
            HTTPException: If the response status is not 200, raises with the response status code and an error detail.
        """

        async def _get():
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        detail = await response.text()
                        raise HTTPException(status_code=response.status, detail=detail)

        return await APIUtils.retry_with_backoff(_get)

    @staticmethod
    async def post(url, data=None):
        """
        Asynchronously send a JSON payload via HTTP POST to a controller endpoint and parse the response.

        Parameters:
            url (str): The full URL of the controller API endpoint.
            data (Any, optional): JSON-serializable payload to include in the POST request (default: None).

        Returns:
            Any: Parsed JSON response when the HTTP status code is 200.

        Raises:
            HTTPException: If the response status is not 200, with the status code and an error detail.
        """

        async def _post():
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        detail = await response.text()
                        raise HTTPException(status_code=response.status, detail=detail)

        return await APIUtils.retry_with_backoff(_post)
