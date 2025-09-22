import asyncio
import glob
import json
import os
import shutil
from nebula.utils import DockerUtils, APIUtils
import docker
from nebula.controller.federation.federation_controller import FederationController
from nebula.controller.federation.scenario_builder import ScenarioBuilder
from nebula.controller.federation.utils_requests import factory_requests_path
from nebula.controller.federation.utils_requests import NodeUpdateRequest, NodeDoneRequest
from typing import Dict
from fastapi import Request
from nebula.config.config import Config
from nebula.core.utils.certificate import generate_ca_certificate
from nebula.core.utils.locker import Locker

class NebulaFederationDocker():
    def __init__(self):
        self.scenario_name = ""
        self.participants_alive = 0
        self.round_per_participant = {}
        self.additionals_participants = {}
        self.additionals_deployables = []
        self.config = Config(entity="FederationController")
        self.network_name = ""
        self.base_network_name = ""
        self.base = ""
        self.last_index_deployed: int = 0
        self.federation_round: int = 0
        self.federation_deployment_lock = Locker("federation_deployment_lock", async_lock=True)
        self.participants_alive_lock = Locker("participants_alive_lock", async_lock=True)

    async def get_additionals_to_be_deployed(self, config) -> list:
        async with self.federation_deployment_lock:
            if not self.additionals_participants:
                return False
            
            participant_idx = int(config["device_args"]["idx"])
            participant_round = int(config["federation_args"]["round"])
            self.round_per_participant[participant_idx] = participant_round
            self.federation_round = min(self.round_per_participant.values())
            
            self.additionals_deployables = [
                idx
                for idx, round in self.additionals_participants.items() 
                if self.federation_round >= round
            ]
            
            additionals_deployables = self.additionals_deployables.copy()
            for idx in additionals_deployables:
                self.additionals_participants.pop(idx)
            return additionals_deployables
        
    async def is_experiment_finish(self):
        async with self.participants_alive_lock:
            self.participants_alive -= 1
        if self.participants_alive <= 0: 
            return True 
        else: 
            return False 

class DockerFederationController(FederationController):
    
    def __init__(self, hub_url, logger):
        super().__init__(hub_url, logger)
        self.root_path = ""
        self.host_platform = ""
        self.config_dir = ""
        self.log_dir = ""
        self.cert_dir = ""
        self.advanced_analytics = ""
        self.url = ""
        self._nebula_federations_pool: dict[str, NebulaFederationDocker] = {}
        self._federations_dict_lock = Locker("federations_dict_lock", async_lock=True)
        
    @property
    def nfp(self):
        """Nebula Federations Pool"""
        return self._nebula_federations_pool

    """                                             ###############################
                                                    #      ENDPOINT CALLBACKS     #
                                                    ###############################
    """

    async def run_scenario(self, federation_id: str, scenario_data: Dict, user: str):
        #TODO maintain files on memory, not read them again
        federation = await self._add_nebula_federation_to_pool(federation_id, user)
        id = ""
        if federation:
            scenario_builder = ScenarioBuilder(federation_id)
            await self._initialize_scenario(scenario_builder, scenario_data, federation)
            generate_ca_certificate(dir_path=self.cert_dir)
            await self._load_configuration_and_start_nodes(scenario_builder, federation)
            self._start_initial_nodes(scenario_builder, federation)
            id = scenario_builder.get_scenario_name()
            try:
                nebula_federation = self.nfp[federation_id]
                nebula_federation.scenario_name = id
            except Exception as e:
                self.logger.info(f"ERROR: federation ID: ({federation_id}) not found on pool..")
                return None
        else:
             self.logger.info(f"ERROR: federation ID: ({federation_id}) already exists..")
        return id
         
    async def stop_scenario(self, federation_id: str):
        """
        Remove all participant containers and the scenario network.
        Reads ALL scenario.metadata and removes all listed containers and the network, then deletes the metadata file.
        Also forcibly stops and removes any containers still attached to the network before removing it.
        """
        federation_scenario_name = await self._remove_nebula_federation_from_pool(federation_id)
        if not federation_scenario_name:
            return False
        
        # Try multiple possible config directory locations. This depends on where the user called the function from.
        possible_config_dirs = [
            os.environ.get("NEBULA_CONFIG_DIR"),
            "/nebula/app/config",
            "./app/config",
            os.path.join(os.getcwd(), "app", "config"),
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "app", "config"),
        ]

        config_dir = None
        for dir_path in possible_config_dirs:
            if dir_path and os.path.exists(dir_path):
                config_dir = dir_path
                break

        if not config_dir:
            self.logger.info("No valid config directory found, skipping cleanup")
            return

        scenario_dirs = []
        self.logger.info(f"Config directory: {config_dir}")
        if os.path.exists(config_dir):
            for item in os.listdir(config_dir):
                scenario_path = os.path.join(config_dir, item)
                if os.path.isdir(scenario_path):
                    metadata_file = os.path.join(scenario_path, "scenario.metadata")
                    if os.path.exists(metadata_file):
                        scenario_dirs.append(scenario_path)

        self.logger.info(f"Removing scenario containers for {scenario_dirs}")
        if not scenario_dirs:
            self.logger.info("No active scenarios found to clean up")
            return

        client = docker.from_env()

        for scenario_dir in scenario_dirs:
            if scenario_dir != federation_scenario_name:
                continue
            
            metadata_path = os.path.join(scenario_dir, "scenario.metadata")
            if not os.path.exists(metadata_path):
                self.logger.info(f"Skipping {scenario_dir} - no scenario.metadata found")
                continue

            with open(metadata_path) as f:
                meta = json.load(f)

            # Remove containers listed in metadata
            for name in meta.get("containers", []):
                try:
                    container = client.containers.get(name)
                    container.remove(force=True)
                    self.logger.info(f"Removed scenario container {name}")
                except Exception as e:
                    self.logger.info(f"Could not remove scenario container {name}: {e}")

            # Remove network, but first forcibly remove any containers still attached
            network_name = meta.get("network")
            if network_name:
                try:
                    network = client.networks.get(network_name)
                    attached_containers = network.attrs.get("Containers") or {}
                    for container_id in attached_containers:
                        try:
                            c = client.containers.get(container_id)
                            c.remove(force=True)
                            self.logger.info(f"Force-removed container {c.name} attached to {network_name}")
                        except Exception as e:
                            self.logger.info(f"Could not force-remove container {container_id}: {e}")
                    network.remove()
                    self.logger.info(f"Removed scenario network {network_name}")
                except Exception as e:
                    self.logger.info(f"Could not remove scenario network {network_name}: {e}")

            # Remove metadata file
            try:
                os.remove(metadata_path)
            except Exception as e:
                self.logger.info(f"Could not remove scenario.metadata: {e}")
                
            if scenario_dir == federation_scenario_name:
                break
                
        return True #TODO care about cases

    async def update_nodes(self, federation_id: str, node_update_request: NodeUpdateRequest):
        config = node_update_request.config
        scenario_name = config["scenario_args"]["name"]
        fed_id = config["scenario_args"]["federation_id"]

        try:
            nebula_federation = self.nfp[fed_id]
            self.logger.info(f"Update received from node on federation ID: ({fed_id})")
            last_fed_round = nebula_federation.federation_round
            additionals = await nebula_federation.get_additionals_to_be_deployed(config) # It modifies if neccesary the federation round
            if additionals:
                current_fed_round = nebula_federation.federation_round
                adds_deployed = set()
                if current_fed_round != last_fed_round:
                    self.logger.info(f"Federation Round updating for ID: ({fed_id}), current value: {current_fed_round}")
                    for index in additionals:
                        if index in adds_deployed:
                            continue
                        
                        for idx, node in enumerate(nebula_federation.config.participants):
                            if index == idx:
                                if index in additionals:
                                    self.logger.info(f"Deploying additional participant: {index}")
                                    deployed_successfully = self._start_node(nebula_federation.scenario_name, node, nebula_federation.network_name, nebula_federation.base_network_name, nebula_federation.base, nebula_federation.last_index_deployed, nebula_federation)
                                    if deployed_successfully:
                                        self.logger.info(f"Deployment successfully for additional participant: {index}")
                                    nebula_federation.last_index_deployed += 1
                                    #additionals.remove(index)
                                    adds_deployed.add(index)
            payload = node_update_request.model_dump()
            asyncio.create_task(self._send_to_hub("update", payload, federation_id=fed_id))
            return {"message": "Node updated successfully in Federation Controller"}
        except Exception as e:
            self.logger.info(f"ERROR: federation ID: ({fed_id}), {e}")
            return {"message": "Node updated failed in Federation Controller"} 

    async def node_done(self, federation_id: str, node_done_request: NodeDoneRequest):
        nebula_federation = self.nfp[federation_id]
        self.logger.info(f"Node-Done received from node on federation ID: ({federation_id})")

        if await nebula_federation.is_experiment_finish():
            payload = node_done_request.model_dump()
            self.logger.info(f"All nodes have finished on federation ID: ({federation_id}), reporting to hub..")
            await self._remove_nebula_federation_from_pool(federation_id)
            asyncio.create_task(self._send_to_hub("finish", payload, federation_id=federation_id))

        payload = node_done_request.model_dump()
        asyncio.create_task(self._send_to_hub("done", payload, federation_id=federation_id))
        return {"message": "Nodes done received successfully"}

    """                                             ###############################
                                                    #       FUNCTIONALITIES       #
                                                    ###############################
    """
    
    async def _add_nebula_federation_to_pool(self, federation_id: str, user: str):
        fed = None
        async with self._federations_dict_lock:
            if not federation_id in self.nfp:
                fed = NebulaFederationDocker()
                self.nfp[federation_id] = fed
                self.logger.info(f"SUCCESS: new ID: ({federation_id}) added to the pool")
            else:
               self.logger.info(f"ERROR: trying to add ({federation_id}) to federations pool..")
        return fed 
    
    async def _remove_nebula_federation_from_pool(self, federation_id: str):
        async with self._federations_dict_lock:
            if federation_id in self.nfp:
                federation = self.nfp.pop(federation_id)
                self.logger.info(f"SUCCESS: Federation ID: ({federation_id}) removed from pool")
                return federation.scenario_name
            else:
                self.logger.info(f"ERROR: trying to remove ({federation_id}) from federations pool..")
                return ""

    async def _update_federation_on_pool(self, federation_id: str, user: str, nf: NebulaFederationDocker):
        updated = False
        async with self._federations_dict_lock:
            if not federation_id in self.nfp:
                self.nfp[federation_id] = nf
                updated = True
                self.logger.info(f"UPDATED: federation: ({federation_id}) successfully updated")
            else:
               self.logger.info(f"ERROR: trying to update ({federation_id}) on federations pool..")
        return updated 
        
    async def _send_to_hub(self, path, payload, scenario_name="",  federation_id="" ):
        try:
            url_request = self._hub_url + factory_requests_path(path, scenario_name, federation_id)
            # self.logger.info(f"Sending to hub, url: {url_request}")
            # self.logger.info(f"payload sent to hub, data: {payload}")
            await APIUtils.post(url_request, payload)
        except Exception as e:
            self.logger.info(f"Failed to send update to Hub: {e}")

    async def _initialize_scenario(self, sb: ScenarioBuilder, scenario_data, federation: NebulaFederationDocker):
        # Initialize Scenario builder using scenario_data from user
        self.logger.info("🔧  Initializing Scenario Builder using scenario data")
        sb.set_scenario_data(scenario_data)
        scenario_name = sb.get_scenario_name()
        
        self.root_path = os.environ.get("NEBULA_ROOT_HOST")
        self.host_platform = os.environ.get("NEBULA_HOST_PLATFORM")
        self.config_dir = os.path.join(os.environ.get("NEBULA_CONFIG_DIR"), scenario_name)
        self.log_dir = os.environ.get("NEBULA_LOGS_DIR")
        self.cert_dir = os.environ.get("NEBULA_CERTS_DIR")
        self.advanced_analytics = os.environ.get("NEBULA_ADVANCED_ANALYTICS", "False") == "True"
        #self.config = Config(entity="FederationController")
        self.env_tag = os.environ.get("NEBULA_ENV_TAG", "dev")
        self.prefix_tag = os.environ.get("NEBULA_PREFIX_TAG", "dev")
        self.user_tag = os.environ.get("NEBULA_USER_TAG", os.environ.get("USER", "unknown"))
        
        self.url = f"{os.environ.get('NEBULA_CONTROLLER_HOST')}:{os.environ.get('NEBULA_FEDERATION_CONTROLLER_PORT')}"
        
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
        self.logger.info("🔧  Building general configuration")
        sb.build_general_configuration()
        self.logger.info("✅  Building general configuration done")
        
        # Create participant configs and .json
        for index, (_, node) in enumerate(sb.get_federation_nodes().items()):
            self.logger.info(f"Creating .json file for participant: {index}, Configuration: {node}")
            node_config = node
            try:
                participant_file = os.path.join(self.config_dir, f"participant_{node_config['id']}.json")
                self.logger.info(f"Filename: {participant_file}")
                os.makedirs(os.path.dirname(participant_file), exist_ok=True)
            except Exception as e:
                 self.logger.info(f"ERROR while creating files: {e}")
                 
            try:         
                participant_config = sb.build_scenario_config_for_node(index, node)
                #self.logger.info(f"dictionary: {participant_config}")
            except Exception as e:
                 self.logger.info(f"ERROR while building configuration for node: {e}")

            try:
                with open(participant_file, "w") as f:
                    json.dump(participant_config, f, sort_keys=False, indent=2)
                os.chmod(participant_file, 0o777)
            except Exception as e:
                 self.logger.info(f"ERROR while dumping configuration into files: {e}")

        self.logger.info("✅  Initializing Scenario Builder done")
                
    async def _load_configuration_and_start_nodes(self, sb: ScenarioBuilder, federation: NebulaFederationDocker):
        self.logger.info("🔧  Loading Scenario configuration...")
        # Get participants configurations
        participant_files = glob.glob(f"{self.config_dir}/participant_*.json")
        participant_files.sort()
        if len(participant_files) == 0:
            raise ValueError("No participant files found in config folder")

        federation.config.set_participants_config(participant_files)
        n_nodes = len(participant_files)
        #self.logger.info(f"Number of nodes: {n_nodes}")
        
        sb.create_topology_manager(federation.config)
        
        # Update participants configuration
        is_start_node = False
        config_participants = []
        
        additional_participants = sb.get_additional_nodes()
        additional_nodes = len(additional_participants) if additional_participants else 0
        #self.logger.info(f"######## nodes: {n_nodes} + additionals: {additional_nodes} ######")
        
        participant_files.sort(key=lambda x: int(x.split("_")[-1].split(".")[0]))
        
        # Initial participants
        self.logger.info("🔧  Building preload configuration for initial nodes...")
        for i in range(n_nodes):
            try:
                with open(f"{self.config_dir}/participant_" + str(i) + ".json") as f:
                    participant_config = json.load(f)
            except Exception as e:
                self.logger.info(f"ERROR: open/load participant .json")

            self.logger.info(f"Building preload conf for participant {i}")
            try:
                sb.build_preload_initial_node_configuration(i, participant_config, self.log_dir, self.config_dir, self.cert_dir, self.advanced_analytics)
            except Exception as e:
                self.logger.info(f"ERROR: cannot build preload configuration")

            try:
                with open(f"{self.config_dir}/participant_" + str(i) + ".json", "w") as f:
                    json.dump(participant_config, f, sort_keys=False, indent=2)
            except Exception as e:
                self.logger.info(f"ERROR: cannot dump preload configuration into participant .json file")

            config_participants.append((
                participant_config["network_args"]["ip"],
                participant_config["network_args"]["port"],
                participant_config["device_args"]["role"],
            ))
            if participant_config["device_args"]["start"]:
                if not is_start_node:
                    is_start_node = True
                else:
                    raise ValueError("Only one node can be start node")

        self.logger.info("✅  Building preload configuration for initial nodes done")
            
        federation.config.set_participants_config(participant_files)
        
        # Add role to the topology (visualization purposes)
        sb.visualize_topology(config_participants, path=f"{self.config_dir}/topology.png", plot=False)
        
        # Additional participants
        self.logger.info("🔧  Building preload configuration for additional nodes...")
        additional_participants_files = []
        if additional_participants:
            last_participant_file = participant_files[-1]
            last_participant_index = len(participant_files)

            for i, _ in enumerate(additional_participants):
                additional_participant_file = f"{self.config_dir}/participant_{last_participant_index + i}.json"
                shutil.copy(last_participant_file, additional_participant_file)

                with open(additional_participant_file) as f:
                    participant_config = json.load(f)

                self.logger.info(f"Configuration | additional nodes |  participant: {n_nodes + i}")
                sb.build_preload_additional_node_configuration(last_participant_index, i, participant_config)
            
                with open(additional_participant_file, "w") as f:
                    json.dump(participant_config, f, sort_keys=False, indent=2)

                additional_participants_files.append(additional_participant_file)

        if additional_participants_files:
            federation.config.add_participants_config(additional_participants_files)

        if additional_participants:
            n_nodes += len(additional_participants)

        self.logger.info("✅  Building preload configuration for additional nodes done")
        self.logger.info("✅  Loading Scenario configuration done")
        
        # Build dataset    
        dataset = sb.configure_dataset(self.config_dir)
        self.logger.info(f"🔧  Splitting {sb.get_dataset_name()} dataset...")
        dataset.initialize_dataset()
        self.logger.info(f"✅  Splitting {sb.get_dataset_name()} dataset... Done")

    def _get_network_name(self, suffix: str) -> str:
        """
        Generate a standardized network name using tags.
        Args:
            suffix (str): Suffix for the network (default: 'net-base').
        Returns:
            str: The composed network name.
        """
        return f"{self.env_tag}_{self.prefix_tag}_{self.user_tag}_{suffix}"
    
    def _get_participant_container_name(self, scenario_name, idx: int) -> str:
        """
        Generate a standardized container name for a participant using tags.
        Args:
            idx (int): The participant index.
        Returns:
            str: The composed container name.
        """
        return f"{self.env_tag}_{self.prefix_tag}_{self.user_tag}_{scenario_name}_participant{idx}"

    def _start_initial_nodes(self, sb: ScenarioBuilder, federation: NebulaFederationDocker):
        self.logger.info("Starting nodes using Docker Compose...")
        federation.network_name = self._get_network_name(f"{sb.get_scenario_name()}-net-scenario")
        federation.base_network_name = self._get_network_name("net-base")

        # Create the Docker network
        federation.base = DockerUtils.create_docker_network(federation.network_name)
  
        federation.config.participants.sort(key=lambda x: x["device_args"]["idx"])
        federation.last_index_deployed = 2
        for idx, node in enumerate(federation.config.participants):
            
            if node["deployment_args"]["additional"]:
                federation.additionals_participants[idx] = int(node["deployment_args"]["deployment_round"])
                federation.participants_alive += 1
                self.logger.info(f"Participant {idx} is additional. Round of deployment: {int(node['deployment_args']['deployment_round'])}")
            else:
                # deploy initial nodes
                self.logger.info(f"Deployment starting for participant {idx}")
                federation.round_per_participant[idx] = 0
                deployed_successfully = self._start_node(sb.get_scenario_name(), node, federation.network_name, federation.base_network_name, federation.base, federation.last_index_deployed, federation)
                if deployed_successfully:
                    federation.last_index_deployed += 1
                    federation.participants_alive += 1
                        
    def _start_node(self, scenario_name, node, network_name, base_network_name, base, i, federation: NebulaFederationDocker):
        success = True
        client = docker.from_env()

        federation.config.participants.sort(key=lambda x: x["device_args"]["idx"])
        container_ids = []
        container_names = []  # Track names for metadata

        image = "nebula-core"
        name = self._get_participant_container_name(scenario_name, node["device_args"]["idx"])
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
            f"{start_command} && ifconfig && echo '{base}.1 host.docker.internal' >> /etc/hosts && python /nebula/nebula/core/node.py /nebula/app/config/{scenario_name}/participant_{node['device_args']['idx']}.json",
        ]
        networking_config = client.api.create_networking_config({
            network_name: client.api.create_endpoint_config(
                ipv4_address=f"{base}.{i}",
            ),
            base_network_name: client.api.create_endpoint_config(),
        })
        node["tracking_args"]["log_dir"] = "/nebula/app/logs"
        node["tracking_args"]["config_dir"] = f"/nebula/app/config/{scenario_name}"
        node["scenario_args"]["controller"] = self.url
        node["scenario_args"]["deployment"] = "docker"
        node["security_args"]["certfile"] = f"/nebula/app/certs/participant_{node['device_args']['idx']}_cert.pem"
        node["security_args"]["keyfile"] = f"/nebula/app/certs/participant_{node['device_args']['idx']}_key.pem"
        node["security_args"]["cafile"] = "/nebula/app/certs/ca_cert.pem"
        node = json.loads(json.dumps(node).replace("192.168.50.", f"{base}."))  # TODO change this
        try:
            existing = client.containers.get(name)
            self.logger.info(f"Container {name} already exists. Deployment may fail or cause conflicts.")
            success = False
        except docker.errors.NotFound:
            pass  # No conflict, safe to proceed
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
            success = False
            self.logger.info(f"Creating container {name}: {e}")
        try:
            client.api.start(container_id)
            container_ids.append(container_id)
            container_names.append(name)
            self.logger.info(f"Adding name: {name} for metadata")
        except Exception as e:
            success = False
            self.logger.info(f"Starting participant {name} error: {e}")
            
        # Write scenario-level metadata for cleanup
        scenario_metadata = {"containers": container_names, "network": network_name}
        with open(os.path.join(self.config_dir, "scenario.metadata"), "a") as f:
            if i == 2:
                json.dump(scenario_metadata, f, indent=2)
            else:
                with open(os.path.join(self.config_dir, "scenario.metadata"), "r") as f:
                    metadata = json.load(f)
                metadata["containers"].extend(container_names)
                with open(os.path.join(self.config_dir, "scenario.metadata"), "w") as f:
                    json.dump(metadata, f, indent=2)
        
        return success