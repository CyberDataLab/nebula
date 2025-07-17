import glob
import json
import os
import shutil
from nebula.controller.federation.federation_controller import FederationController
from typing import Dict
from fastapi import Request
from nebula.config.config import Config
from nebula.core.utils.certificate import generate_ca_certificate, generate_certificate


class DockerFederationController(FederationController):
    
    def __init__(self, wa_controller_url, logger):
        super.__init__(wa_controller_url, logger)
        self.root_path = ""
        self.host_platform = ""
        self.config_dir = ""
        self.log_dir = ""
        self.cert_dir = ""
        self.advanced_analytics = ""
        self.controller = ""
        self.config = Config(entity="scenarioManagement")
        
    #TODO remove unnecesary parameters role and user
    async def run_scenario(self, scenario_data: Dict, role: str, user: str):
        #TODO maintain files on memory, not read them again
        await self._initialize_scenario(scenario_data)
        generate_ca_certificate(dir_path=self.cert_dir)
        await self._load_configuration_and_start_nodes()
         
    async def stop_scenario(self, scenario_name: str, username: str, all: bool):
        pass

    async def remove_scenario(self, scenario_name: str):
        pass

    async def update_nodes(self, scenario_name: str, request: Request):
        pass
    
    async def _initialize_scenario(self, scenario_data):
        # Initialize Scenario builder using scenario_data from user
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
        self.sb.build_general_configuration()
        
        # Create participant configs and .json
        for index, node in enumerate(self.sb.get_federation_nodes().keys()):
            node_config = node
            participant_file = os.path.join(self.config_dir, f"participant_{node_config['id']}.json")
            os.makedirs(os.path.dirname(participant_file), exist_ok=True)
            os.chmod(participant_file, 0o777)
            
            participant_config = self.sb.build_scenario_config_for_node(index, node)
            with open(participant_file, "w") as f:
                json.dump(participant_config, f, sort_keys=False, indent=2)
                
    async def _load_configuration_and_start_nodes(self):
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
            
        if not is_start_node:
            raise ValueError("No start node found")
        self.config.set_participants_config(participant_files)
        
        # Add role to the topology (visualization purposes)
        self.sb.visualize_topology(config_participants, path=f"{self.config_dir}/topology.png", plot=False)
        
        # Additional participants
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
        
        # Build dataset    
        dataset = self.sb.configure_dataset()