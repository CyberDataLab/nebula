import logging
import os
import socket

import docker


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

    @classmethod
    def remove_docker_network(cls, network_name):
        """
        Removes a Docker network by name.

        Args:
            network_name (str): Name of the Docker network to remove.

        Returns:
            None
        """
        try:
            # Connect to Docker
            client = docker.from_env()

            # Get the network by name
            network = client.networks.get(network_name)

            # Remove the network
            network.remove()

            logging.info(f"Network {network_name} removed successfully.")
        except docker.errors.NotFound:
            logging.exception(f"Network {network_name} not found.")
        except docker.errors.APIError:
            logging.exception("Error interacting with Docker")
        except Exception:
            logging.exception("Unexpected error")

    @classmethod
    def remove_docker_networks_by_prefix(cls, prefix):
        """
        Removes all Docker networks whose names start with the given prefix.

        Args:
            prefix (str): Prefix string to match network names.

        Returns:
            None
        """
        try:
            # Connect to Docker
            client = docker.from_env()

            # List all networks
            networks = client.networks.list()

            # Filter and remove networks with names starting with the prefix
            for network in networks:
                if network.name.startswith(prefix):
                    network.remove()
                    logging.info(f"Network {network.name} removed successfully.")

        except docker.errors.NotFound:
            logging.info(f"One or more networks with prefix {prefix} not found.")
        except docker.errors.APIError:
            logging.info("Error interacting with Docker")
        except Exception:
            logging.info("Unexpected error")

    @classmethod
    def remove_containers_by_prefix(cls, prefix):
        """
        Removes all Docker containers whose names start with the given prefix.
        Containers are forcibly removed even if they are running.

        Args:
            prefix (str): Prefix string to match container names.

        Returns:
            None
        """
        try:
            # Connect to Docker client
            client = docker.from_env()

            containers = client.containers.list(all=True)  # `all=True` to include stopped containers

            # Iterate through containers and remove those with the matching prefix
            for container in containers:
                if container.name.startswith(prefix):
                    logging.info(f"Removing container: {container.name}")
                    container.remove(force=True)  # force=True to stop and remove if running
                    logging.info(f"Container {container.name} removed successfully.")

        except docker.errors.APIError:
            logging.exception("Error interacting with Docker")
        except Exception:
            logging.exception("Unexpected error")
