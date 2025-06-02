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
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
            s.close()
            return True
        except OSError:
            return False

    @classmethod
    def find_free_port(cls, start_port=49152, end_port=65535):
        for port in range(start_port, end_port + 1):
            if cls.is_port_open(port):
                return port
        return None


class DockerUtils:
    """
    Utility class for Docker operations.
    """

    @classmethod
    def create_docker_network(cls, network_name, subnet=None, prefix=24):
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
    def remove_docker_network(cls, network_name):
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
