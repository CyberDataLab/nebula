import asyncio
import glob
import json
import os
import shutil
from nebula.utils import APIUtils
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

class NebulaFederationProcesses():
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

class ProcessesFederationController(FederationController):
    def __init__(self, hub_url, logger):
        super().__init__(hub_url, logger)
        self.root_path = ""
        self.host_platform = ""
        self.config_dir = ""
        self.log_dir = ""
        self.cert_dir = ""
        self.advanced_analytics = ""
        self.url = ""
         
        self._nebula_federations_pool: dict[tuple[str,str], NebulaFederationProcesses] = {}
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
         
    async def stop_scenario(self, federation_id: str = ""):
        """
        Stop running participant nodes by removing the scenario command files.

        This method deletes the 'current_scenario_commands.sh' (or '.ps1' on Windows)
        file associated with a scenario. Removing this file signals the nodes to stop
        by terminating their processes.

        Args:
            scenario_name (str, optional): The name of the scenario to stop. If None,
                all scenarios' command files will be removed.

        Notes:
            - If the environment variable NEBULA_CONFIG_DIR is not set, a default
              configuration directory path is used.
            - Supports both Linux/macOS ('.sh') and Windows ('.ps1') script files.
            - Any errors during file removal are logged with the traceback.
        """
        federation_name = await self._remove_nebula_federation_from_pool(federation_id)
        if not federation_name:
            return False
        
        # When stopping the nodes, we need to remove the current_scenario_commands.sh file -> it will cause the nodes to stop using PIDs
        try:
            nebula_config_dir = os.environ.get("NEBULA_CONFIG_DIR")
            if not nebula_config_dir:
                current_dir = os.path.dirname(__file__)
                nebula_base_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))
                nebula_config_dir = os.path.join(nebula_base_dir, "app", "config")
                self.logger.info(f"NEBULA_CONFIG_DIR not found. Using default path: {nebula_config_dir}")
            if federation_id:
                if os.environ.get("NEBULA_HOST_PLATFORM") == "windows":
                    scenario_commands_file = os.path.join(
                        nebula_config_dir, federation_name, "current_scenario_commands.ps1"
                    )
                else:
                    scenario_commands_file = os.path.join(
                        nebula_config_dir, federation_name, "current_scenario_commands.sh"
                    )
                if os.path.exists(scenario_commands_file):
                    os.remove(scenario_commands_file)
            else:
                if os.environ.get("NEBULA_HOST_PLATFORM") == "windows":
                    files = glob.glob(
                        os.path.join(nebula_config_dir, "**/current_scenario_commands.ps1"), recursive=True
                    )
                else:
                    files = glob.glob(
                        os.path.join(nebula_config_dir, "**/current_scenario_commands.sh"), recursive=True
                    )
                for file in files:
                    os.remove(file)
            return True
        except Exception as e:
            self.logger.exception(f"Error while removing current_scenario_commands.sh file: {e}")
        return False

    async def update_nodes(self, federation_id: str, node_update_request: NodeUpdateRequest):
        config = node_update_request.config
        fed_id = config["scenario_args"]["federation_id"]
        scenario_name = config["scenario_args"]["name"]

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
                                    #TODO additionals not working
                                    self._start_node(node, nebula_federation.network_name, nebula_federation.base_network_name, nebula_federation.base, nebula_federation.last_index_deployed, nebula_federation, additional=True)
                                    nebula_federation.last_index_deployed += 1
                                    additionals.remove(index)
                                    adds_deployed.add(index)
            payload = node_update_request.model_dump()
            asyncio.create_task(self._send_to_hub("update", payload, federation_id=fed_id))
            return {"message": "Node updated successfully in Federation Controller"}
        except Exception as e:
            self.logger.info(f"ERROR: federation ID: ({fed_id}) not found on pool..")
            return {"message": "Node updated failed in Federation Controller, ID not found.."}

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
                fed = NebulaFederationProcesses()
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
    
    async def _send_to_hub(self, path, payload, scenario_name="",  federation_id="" ):
        try:
            url_request = self._hub_url + factory_requests_path(path, scenario_name, federation_id)
            # self.logger.info(f"Seding to hub, url: {url_request}")
            # self.logger.info(f"payload sent to hub, data: {payload}")
            await APIUtils.post(url_request, payload)
        except Exception as e:
            self.logger.info(f"Failed to send update to Hub: {e}")

    async def _initialize_scenario(self, sb: ScenarioBuilder, scenario_data, federation: NebulaFederationProcesses):
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
        # self.config = Config(entity="scenarioManagement")
        self.env_tag = os.environ.get("NEBULA_ENV_TAG", "dev")
        self.prefix_tag = os.environ.get("NEBULA_PREFIX_TAG", "dev")
        self.user_tag = os.environ.get("NEBULA_USER_TAG", os.environ.get("USER", "unknown"))
        
        self.url = f"127.0.0.1:{os.environ.get('NEBULA_FEDERATION_CONTROLLER_PORT')}"
        
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
                
    async def _load_configuration_and_start_nodes(self, sb: ScenarioBuilder, federation: NebulaFederationProcesses):
        self.logger.info("🔧  Loading Scenario configuration...")
        # Get participants configurations
        participant_files = glob.glob(f"{self.config_dir}/participant_*.json")
        participant_files.sort()
        if len(participant_files) == 0:
            raise ValueError("No participant files found in config folder")

        federation.config.set_participants_config(participant_files)
        n_nodes = len(participant_files)
        self.logger.info(f"Number of nodes: {n_nodes}")
        
        sb.create_topology_manager(federation.config)
        
        # Update participants configuration
        is_start_node = False
        config_participants = []
        
        additional_participants = sb.get_additional_nodes()
        additional_nodes = len(additional_participants) if additional_participants else 0
        
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

    def _start_initial_nodes(self, sb: ScenarioBuilder, federation: NebulaFederationProcesses):
        self.logger.info("Starting nodes as processes...")
        self.logger.info(f"Number of participants: {len(federation.config.participants)}")
        federation.config.participants.sort(key=lambda x: x["device_args"]["idx"])
        federation.last_index_deployed = 2
        
        commands = ""
        commands = self._build_initial_commands()
        if not commands:
            self.logger.info("ERROR: Cannot create commands file, abort..")
            return
        
        for idx, node in enumerate(federation.config.participants):    
            if node["deployment_args"]["additional"]:
                federation.additionals_participants[idx] = int(node["deployment_args"]["deployment_round"])
                federation.participants_alive += 1
                self.logger.info(f"Participant {idx} is additional. Round of deployment: {int(node['deployment_args']['deployment_round'])}")
            else:
                # deploy initial nodes
                self.logger.info(f"Deployment starting for participant {idx}")
                federation.round_per_participant[idx] = 0
                node_command = self._start_node(sb, node, federation.network_name, federation.base_network_name, federation.base, federation.last_index_deployed, federation)
                commands += node_command
                if node_command:
                    federation.last_index_deployed += 1
                    federation.participants_alive += 1
                    
        if federation.config.participants and commands:
            self._write_commands_on_file(commands)
        else:
            self.logger.info("ERROR: No commands on a proccesses deployment..")
                      
    def _start_node(self, sb: ScenarioBuilder, node, network_name, base_network_name, base, i, federation: NebulaFederationProcesses, additional=False):
        self.processes_root_path = os.path.join(os.path.dirname(__file__), "..", "..")
        node_idx = node['device_args']['idx']
        # Include additional config to the participants
        node["tracking_args"]["log_dir"] = os.path.join(self.root_path, "app", "logs")
        node["tracking_args"]["config_dir"] = os.path.join(self.root_path, "app", "config", sb.get_scenario_name())
        node["scenario_args"]["controller"] = self.url
        node["scenario_args"]["deployment"] = sb.get_deployment()
        node["security_args"]["certfile"] = os.path.join(
            self.root_path, "app", "certs", f"participant_{node['device_args']['idx']}_cert.pem"
        )
        node["security_args"]["keyfile"] = os.path.join(
            self.root_path, "app", "certs", f"participant_{node['device_args']['idx']}_key.pem"
        )
        node["security_args"]["cafile"] = os.path.join(self.root_path, "app", "certs", "ca_cert.pem")
        # Write the config file in config directory
        with open(f"{self.config_dir}/participant_{node['device_args']['idx']}.json", "w") as f:
            json.dump(node, f, indent=4)

        self.logger.info(f"Configuration file created successfully: {node_idx}")
        commands = ""
        try:
            if self.host_platform == "windows":
                if node["device_args"]["start"]:
                    commands += "Start-Sleep -Seconds 10\n"
                else:
                    commands += "Start-Sleep -Seconds 2\n"
                commands += f'Write-Host "Running node {node["device_args"]["idx"]}..."\n'
                commands += f'$OUT_FILE = "{self.root_path}\\app\\logs\\{sb.get_scenario_name()}\\participant_{node["device_args"]["idx"]}.out"\n'
                commands += f'$ERROR_FILE = "{self.root_path}\\app\\logs\\{sb.get_scenario_name()}\\participant_{node["device_args"]["idx"]}.err"\n'
                # Use Start-Process for executing Python in background and capture PID
                commands += f"""$process = Start-Process -FilePath "python" -ArgumentList "{self.root_path}\\nebula\\core\\node.py {self.root_path}\\app\\config\\{sb.get_scenario_name()}\\participant_{node["device_args"]["idx"]}.json" -PassThru -NoNewWindow -RedirectStandardOutput $OUT_FILE -RedirectStandardError $ERROR_FILE
                Add-Content -Path $PID_FILE -Value $process.Id
                """
            else:
                if node["device_args"]["start"]:
                    commands += "sleep 10\n"
                else:
                    commands += "sleep 2\n"
                commands += f'echo "Running node {node["device_args"]["idx"]}..."\n'
                commands += f"OUT_FILE={self.root_path}/app/logs/{sb.get_scenario_name()}/participant_{node['device_args']['idx']}.out\n"
                commands += f"python {self.root_path}/nebula/core/node.py {self.root_path}/app/config/{sb.get_scenario_name()}/participant_{node['device_args']['idx']}.json &\n"
                commands += "echo $! >> $PID_FILE\n\n"
        except Exception as e:
            raise Exception(f"Error starting nodes as processes: {e}")
        
        return commands
       
    def _build_initial_commands(self):
        commands = ""
        try:
            if self.host_platform == "windows":
                commands = """
                $ParentDir = Split-Path -Parent $PSScriptRoot
                $PID_FILE = "$PSScriptRoot\\current_scenario_pids.txt"
                New-Item -Path $PID_FILE -Force -ItemType File

                """
            else:
                commands = '#!/bin/bash\n\nPID_FILE="$(dirname "$0")/current_scenario_pids.txt"\n\n> $PID_FILE\n\n'
        except Exception as e:
            raise Exception(f"Error starting nodes as processes: {e}")
        return commands       
        
    def _write_commands_on_file(self, commands: str):
        try:
            if self.host_platform == "windows":
                commands += 'Write-Host "All nodes started. PIDs stored in $PID_FILE"\n'
                with open(f"{self.config_dir}/current_scenario_commands.ps1", "w") as f:
                    #self.logger.info(f"Process commands: {commands}")
                    f.write(commands)
                os.chmod(f"{self.config_dir}/current_scenario_commands.ps1", 0o755)
            else:
                commands += 'echo "All nodes started. PIDs stored in $PID_FILE"\n'
                with open(f"{self.config_dir}/current_scenario_commands.sh", "w") as f:
                    #self.logger.info(f"Process commands: {commands}")
                    f.write(commands)
                os.chmod(f"{self.config_dir}/current_scenario_commands.sh", 0o755)
        except Exception as e:
            raise Exception(f"Error starting nodes as processes: {e}")