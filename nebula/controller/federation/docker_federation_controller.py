import glob
import json
import os
import shutil
from nebula.utils import DockerUtils, FileUtils
import docker
from nebula.controller.federation.federation_controller import FederationController
from typing import Dict
from fastapi import Request
from nebula.config.config import Config
from nebula.core.utils.certificate import generate_ca_certificate, generate_certificate


class DockerFederationController(FederationController):
    
    def __init__(self, wa_controller_url, logger):
        super.__init__(wa_controller_url, logger)
        self._user = ""
        self.root_path = ""
        self.host_platform = ""
        self.config_dir = ""
        self.log_dir = ""
        self.cert_dir = ""
        self.advanced_analytics = ""
        self.controller = ""
        self.config = Config(entity="scenarioManagement")

    """                                             ###############################
                                                    #      ENDPOINT CALLBACKS     #
                                                    ###############################
    """

    async def run_scenario(self, scenario_data: Dict, role: str, user: str):
        #TODO maintain files on memory, not read them again
        self._user = user
        await self._initialize_scenario(scenario_data)
        generate_ca_certificate(dir_path=self.cert_dir)
        await self._load_configuration_and_start_nodes()
        #self._start_nodes()
         
    async def stop_scenario(self, scenario_name: str, username: str, all: bool):
        pass

    async def remove_scenario(self, scenario_name: str):
        pass

    async def update_nodes(self, scenario_name: str, request: Request):
        pass

    """                                             ###############################
                                                    #       FUNCTIONALITIES       #
                                                    ###############################
    """

    async def _initialize_scenario(self, scenario_data):
        # Initialize Scenario builder using scenario_data from user
        self.logger.info("Initializing Scenario Builder using scenario data")
        self.sb.set_scenario_data(scenario_data)
        scenario_name = self.sb.get_scenario_name()
        
        self.root_path = os.environ.get("NEBULA_ROOT_HOST")
        self.host_platform = os.environ.get("NEBULA_HOST_PLATFORM")
        self.config_dir = os.path.join(os.environ.get("NEBULA_CONFIG_DIR"), scenario_name)
        self.log_dir = os.environ.get("NEBULA_LOGS_DIR")
        self.cert_dir = os.environ.get("NEBULA_CERTS_DIR")
        self.advanced_analytics = os.environ.get("NEBULA_ADVANCED_ANALYTICS", "False") == "True"
        self.config = Config(entity="scenarioManagement")
        
        self.controller = f"{os.environ.get('NEBULA_CONTROLLER_HOST')}:{os.environ.get('NEBULA_CONTROLLER_PORT')}"
        
        # Create Scenario management dirs
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(os.path.join(self.log_dir, scenario_name), exist_ok=True)
        os.makedirs(self.cert_dir, exist_ok=True)

        # Give permissions to the directories
        os.chmod(self.config_dir, 0o777)
        os.chmod(os.path.join(self.log_dir, scenario_name), 0o777)
        os.chmod(self.cert_dir, 0o777)

        # Save the scenario configuration
        scenario_file = os.path.join(self.config_dir, "scenario.json")
        with open(scenario_file, "w") as f:
            json.dump(scenario_data, f, sort_keys=False, indent=2)

        os.chmod(scenario_file, 0o777)

        # Save management settings
        settings = {
            "scenario_name": scenario_name,
            "root_path": self.root_path,
            "config_dir": self.config_dir,
            "log_dir": self.log_dir,
            "cert_dir": self.cert_dir,
            "env": None,
        }

        settings_file = os.path.join(self.config_dir, "settings.json")
        with open(settings_file, "w") as f:
            json.dump(settings, f, sort_keys=False, indent=2)

        os.chmod(settings_file, 0o777)
        
        # Attacks assigment and mobility
        self.logger.info("Building general configuration")
        self.sb.build_general_configuration()
        self.logger.info("Building general configuration done")
        
        # Create participant configs and .json
        for index, node in enumerate(self.sb.get_federation_nodes().keys()):
            node_config = node
            participant_file = os.path.join(self.config_dir, f"participant_{node_config['id']}.json")
            os.makedirs(os.path.dirname(participant_file), exist_ok=True)
            os.chmod(participant_file, 0o777)
            
            participant_config = self.sb.build_scenario_config_for_node(index, node)
            with open(participant_file, "w") as f:
                json.dump(participant_config, f, sort_keys=False, indent=2)

        self.logger.info("Initializing Scenario Builder done")
                
    async def _load_configuration_and_start_nodes(self):
        self.logger.info("Loading Scenario configuration...")
        # Get participants configurations
        participant_files = glob.glob(f"{self.config_dir}/participant_*.json")
        participant_files.sort()
        if len(participant_files) == 0:
            raise ValueError("No participant files found in config folder")

        self.config.set_participants_config(participant_files)
        self.n_nodes = len(participant_files)
        self.logger.info(f"Number of nodes: {self.n_nodes}")
        
        self.sb.create_topology_manager(self.config)
        
        # Update participants configuration
        is_start_node = False
        config_participants = []
        
        additional_participants = self.sb.get_additional_nodes()
        additional_nodes = len(additional_participants) if additional_participants else 0
        self.logger.info(f"######## nodes: {self.n_nodes} + additionals: {additional_nodes} ######")
        
        participant_files.sort(key=lambda x: int(x.split("_")[-1].split(".")[0]))
        
        # Initial participants
        self.logger.info("Building preload configuration for initial nodes...")
        for i in range(self.n_nodes):
            with open(f"{self.config_dir}/participant_" + str(i) + ".json") as f:
                participant_config = json.load(f)
            
            self.sb.build_preload_configuration(i, participant_config, self.log_dir, self.config_dir, self.cert_dir, self.advanced_analytics)
            
            with open(f"{self.config_dir}/participant_" + str(i) + ".json", "w") as f:
                json.dump(participant_config, f, sort_keys=False, indent=2)

            config_participants.append((
                participant_config["network_args"]["ip"],
                participant_config["network_args"]["port"],
                participant_config["device_args"]["role"],
            ))

        self.logger.info("Building preload configuration for initial nodes done")    
        if not is_start_node:
            raise ValueError("No start node found")
        self.config.set_participants_config(participant_files)
        
        # Add role to the topology (visualization purposes)
        self.sb.visualize_topology(config_participants, path=f"{self.config_dir}/topology.png", plot=False)
        
        # Additional participants
        self.logger.info("Building preload configuration for additional nodes...")
        additional_participants_files = []
        if additional_participants:
            last_participant_file = participant_files[-1]
            last_participant_index = len(participant_files)

            for i, _ in enumerate(additional_participants):
                additional_participant_file = f"{self.config_dir}/participant_{last_participant_index + i}.json"
                shutil.copy(last_participant_file, additional_participant_file)

                with open(additional_participant_file) as f:
                    participant_config = json.load(f)

                self.logger.info(f"Configuration | additional nodes |  participant: {self.n_nodes + i + 1}")
                self.sb.build_preload_additional_node_configuration(last_participant_index, i, participant_config)
            
                with open(additional_participant_file, "w") as f:
                    json.dump(participant_config, f, sort_keys=False, indent=2)

                additional_participants_files.append(additional_participant_file)

        if additional_participants_files:
            self.config.add_participants_config(additional_participants_files)

        if additional_participants:
            self.n_nodes += len(additional_participants)

        self.logger.info("Building preload configuration for additional nodes done")
        
        # Build dataset    
        dataset = self.sb.configure_dataset(self.config_dir)
        self.logger.info(f"Splitting {self.sb.get_dataset_name()} dataset...")
        dataset.initialize_dataset()
        self.logger.info(f"Splitting {self.sb.get_dataset_name()} dataset... Done")

    #TODO delay additionals deployment until conditions
    def _start_nodes(self):
        """
        Starts participant nodes as Docker containers using Docker SDK.

        This method performs the following steps:
        - Logs the beginning of the Docker container startup process.
        - Creates a Docker network specific to the current user and scenario.
        - Sorts participant nodes by their index.
        - For each participant node:
            - Sets up environment variables and host configuration,
              enabling GPU support if required.
            - Prepares Docker volume bindings and static network IP assignment.
            - Updates the node configuration, replacing IP addresses as needed,
              and writes the configuration to a JSON file.
            - Creates and starts the Docker container for the node.
            - Logs any exceptions encountered during container creation or startup.

        Raises:
            docker.errors.DockerException: If there are issues communicating with the Docker daemon.
            OSError: If there are issues accessing file system paths for volume binding.
            Exception: For any other unexpected errors during container creation or startup.

        Note:
            - The method assumes Docker and NVIDIA runtime are properly installed and configured.
            - IP addresses in node configurations are replaced with network base dynamically.
        """
        self.logger.info("Starting nodes using Docker Compose...")

        network_name = f"{os.environ.get('NEBULA_CONTROLLER_NAME')}_{str(self._user).lower()}-nebula-net-scenario"

        # Create the Docker network
        base = DockerUtils.create_docker_network(network_name)

        client = docker.from_env()

        self.config.participants.sort(key=lambda x: x["device_args"]["idx"])
        i = 2
        container_ids = []
        for idx, node in enumerate(self.config.participants):
            image = "nebula-core"
            name = f"{os.environ.get('NEBULA_CONTROLLER_NAME')}_{self._user}-participant{node['device_args']['idx']}"

            if node["device_args"]["accelerator"] == "gpu":
                environment = {
                    "NVIDIA_DISABLE_REQUIRE": True,
                    "NEBULA_LOGS_DIR": "/nebula/app/logs/",
                    "NEBULA_CONFIG_DIR": "/nebula/app/config/",
                }
                host_config = client.api.create_host_config(
                    binds=[f"{self.root_path}:/nebula", "/var/run/docker.sock:/var/run/docker.sock"],
                    privileged=True,
                    device_requests=[docker.types.DeviceRequest(driver="nvidia", count=-1, capabilities=[["gpu"]])],
                    extra_hosts={"host.docker.internal": "host-gateway"},
                )
            else:
                environment = {"NEBULA_LOGS_DIR": "/nebula/app/logs/", "NEBULA_CONFIG_DIR": "/nebula/app/config/"}
                host_config = client.api.create_host_config(
                    binds=[f"{self.root_path}:/nebula", "/var/run/docker.sock:/var/run/docker.sock"],
                    privileged=True,
                    device_requests=[],
                    extra_hosts={"host.docker.internal": "host-gateway"},
                )

            volumes = ["/nebula", "/var/run/docker.sock"]

            start_command = "sleep 10" if node["device_args"]["start"] else "sleep 0"
            command = [
                "/bin/bash",
                "-c",
                f"{start_command} && ifconfig && echo '{base}.1 host.docker.internal' >> /etc/hosts && python /nebula/nebula/core/node.py /nebula/app/config/{self.scenario_name}/participant_{node['device_args']['idx']}.json",
            ]

            networking_config = client.api.create_networking_config({
                f"{network_name}": client.api.create_endpoint_config(
                    ipv4_address=f"{base}.{i}",
                ),
                f"{os.environ.get('NEBULA_CONTROLLER_NAME')}_nebula-net-base": client.api.create_endpoint_config(),
            })

            node["tracking_args"]["log_dir"] = "/nebula/app/logs"
            node["tracking_args"]["config_dir"] = f"/nebula/app/config/{self.sb.get_scenario_name()}"
            node["scenario_args"]["controller"] = self.controller
            node["scenario_args"]["deployment"] = "docker"
            node["security_args"]["certfile"] = f"/nebula/app/certs/participant_{node['device_args']['idx']}_cert.pem"
            node["security_args"]["keyfile"] = f"/nebula/app/certs/participant_{node['device_args']['idx']}_key.pem"
            node["security_args"]["cafile"] = "/nebula/app/certs/ca_cert.pem"
            node = json.loads(json.dumps(node).replace("192.168.50.", f"{base}."))  # TODO change this

            # Write the config file in config directory
            with open(f"{self.config_dir}/participant_{node['device_args']['idx']}.json", "w") as f:
                json.dump(node, f, indent=4)

            try:
                container_id = client.api.create_container(
                    image=image,
                    name=name,
                    detach=True,
                    volumes=volumes,
                    environment=environment,
                    command=command,
                    host_config=host_config,
                    networking_config=networking_config,
                )
            except Exception as e:
                self.logger.exception(f"Creating container {name}: {e}")

            try:
                client.api.start(container_id)
                container_ids.append(container_id)
            except Exception as e:
                self.logger.exception(f"Starting participant {name} error: {e}")
            i += 1