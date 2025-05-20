import glob
import hashlib
import json
import logging
import math
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime

import docker
import tensorboard_reducer as tbr

from nebula.addons.blockchain.blockchain_deployer import BlockchainDeployer
from nebula.addons.topologymanager import TopologyManager
from nebula.config.config import Config
from nebula.core.datasets.cifar10.cifar10 import CIFAR10Dataset
from nebula.core.datasets.cifar100.cifar100 import CIFAR100Dataset
from nebula.core.datasets.emnist.emnist import EMNISTDataset
from nebula.core.datasets.fashionmnist.fashionmnist import FashionMNISTDataset
from nebula.core.datasets.mnist.mnist import MNISTDataset
from nebula.core.utils.certificate import generate_ca_certificate, generate_certificate
from nebula.utils import DockerUtils, FileUtils


# Definition of a scenario
class Scenario:
    """
    Class to define a scenario for the NEBULA platform.
    It contains all the parameters needed to create a scenario and run it on the platform.
    """

    def __init__(
        self,
        scenario_title,
        scenario_description,
        deployment,
        federation,
        topology,
        nodes,
        nodes_graph,
        n_nodes,
        matrix,
        dataset,
        iid,
        partition_selection,
        partition_parameter,
        model,
        agg_algorithm,
        rounds,
        logginglevel,
        report_status_data_queue,
        accelerator,
        gpu_id,
        network_subnet,
        network_gateway,
        epochs,
        attacks,
        poisoned_node_percent,
        poisoned_sample_percent,
        poisoned_noise_percent,
        attack_params,
        with_reputation,
        reputation_metrics,
        initial_reputation,
        weighting_factor,
        weight_model_arrival_latency,
        weight_model_similarity,
        weight_num_messages,
        weight_fraction_params_changed,
        # is_dynamic_topology,
        # is_dynamic_aggregation,
        # target_aggregation,
        random_geo,
        latitude,
        longitude,
        mobility,
        mobility_type,
        radius_federation,
        scheme_mobility,
        round_frequency,
        mobile_participants_percent,
        additional_participants,
        schema_additional_participants,
        random_topology_probability,
    ):
        """
        Initialize the scenario.

        Args:
            scenario_title (str): Title of the scenario.
            scenario_description (str): Description of the scenario.
            deployment (str): Type of deployment (e.g., 'docker', 'process').
            federation (str): Type of federation.
            topology (str): Network topology.
            nodes (dict): Dictionary of nodes.
            nodes_graph (dict): Graph of nodes.
            n_nodes (int): Number of nodes.
            matrix (list): Matrix of connections.
            dataset (str): Dataset used.
            iid (bool): Indicator if data is independent and identically distributed.
            partition_selection (str): Method of partition selection.
            partition_parameter (float): Parameter for partition selection.
            model (str): Model used.
            agg_algorithm (str): Aggregation algorithm.
            rounds (int): Number of rounds.
            logginglevel (str): Logging level.
            report_status_data_queue (bool): Indicator to report information about the nodes of the scenario
            accelerator (str): Accelerator used.
            gpu_id (list) : Id list of the used gpu
            network_subnet (str): Network subnet.
            network_gateway (str): Network gateway.
            epochs (int): Number of epochs.
            attacks (list): List of attacks.
            poisoned_node_percent (float): Percentage of poisoned nodes.
            poisoned_sample_percent (float): Percentage of poisoned samples.
            noise_type (str): The type of noise applied by the attack.
            targeted (bool): Indicator if the attack is targeted.
            target_label (int): The label to change when `targeted` is True.
            target_changed_label (int): The label to which `target_label` will be changed .
            attack_params (dict) : Attack parameters.
            with_reputation (bool): Indicator if reputation is used.
            reputation_metrics (list): List of reputation metrics.
            initial_reputation (float): Initial reputation.
            weighting_factor (str): dymanic or static weighting factor.
            weight_model_arrival_latency (float): Weight of model arrival latency.
            weight_model_similarity (float): Weight of model similarity.
            weight_num_messages (float): Weight of number of messages.
            weight_fraction_params_changed (float): Weight of fraction of parameters changed.
            # is_dynamic_topology (bool): Indicator if topology is dynamic.
            # is_dynamic_aggregation (bool): Indicator if aggregation is dynamic.
            # target_aggregation (str): Target aggregation method.
            random_geo (bool): Indicator if random geo is used.
            latitude (float): Latitude for mobility.
            longitude (float): Longitude for mobility.
            mobility (bool): Indicator if mobility is used.
            mobility_type (str): Type of mobility.
            radius_federation (float): Radius of federation.
            scheme_mobility (str): Scheme of mobility.
            round_frequency (int): Frequency of rounds.
            mobile_participants_percent (float): Percentage of mobile participants.
            additional_participants (list): List of additional participants.
            schema_additional_participants (str): Schema for additional participants.
            random_topology_probability (float): Probability for random topology.
        """
        self.scenario_title = scenario_title
        self.scenario_description = scenario_description
        self.deployment = deployment
        self.federation = federation
        self.topology = topology
        self.nodes = nodes
        self.nodes_graph = nodes_graph
        self.n_nodes = n_nodes
        self.matrix = matrix
        self.dataset = dataset
        self.iid = iid
        self.partition_selection = partition_selection
        self.partition_parameter = partition_parameter
        self.model = model
        self.agg_algorithm = agg_algorithm
        self.rounds = rounds
        self.logginglevel = logginglevel
        self.report_status_data_queue = report_status_data_queue
        self.accelerator = accelerator
        self.gpu_id = gpu_id
        self.network_subnet = network_subnet
        self.network_gateway = network_gateway
        self.epochs = epochs
        self.attacks = attacks
        self.poisoned_node_percent = poisoned_node_percent
        self.poisoned_sample_percent = poisoned_sample_percent
        self.poisoned_noise_percent = poisoned_noise_percent
        self.attack_params = attack_params
        self.with_reputation = with_reputation
        self.reputation_metrics = reputation_metrics
        self.initial_reputation = initial_reputation
        self.weighting_factor = weighting_factor
        self.weight_model_arrival_latency = weight_model_arrival_latency
        self.weight_model_similarity = weight_model_similarity
        self.weight_num_messages = weight_num_messages
        self.weight_fraction_params_changed = weight_fraction_params_changed
        # self.is_dynamic_topology = is_dynamic_topology
        # self.is_dynamic_aggregation = is_dynamic_aggregation
        # self.target_aggregation = target_aggregation
        self.random_geo = random_geo
        self.latitude = latitude
        self.longitude = longitude
        self.mobility = mobility
        self.mobility_type = mobility_type
        self.radius_federation = radius_federation
        self.scheme_mobility = scheme_mobility
        self.round_frequency = round_frequency
        self.mobile_participants_percent = mobile_participants_percent
        self.additional_participants = additional_participants
        self.schema_additional_participants = schema_additional_participants
        self.random_topology_probability = random_topology_probability

    def attack_node_assign(
        self,
        nodes,
        federation,
        attack,
        poisoned_node_percent,
        poisoned_sample_percent,
        poisoned_noise_percent,
        attack_params,
    ):
        """Identify which nodes will be attacked"""
        import math
        import random
        import logging

        # Validate input parameters
        def validate_percentage(value, name):
            try:
                value = float(value)
                if not 0 <= value <= 100:
                    raise ValueError(f"{name} must be between 0 and 100")
                return value
            except (TypeError, ValueError) as e:
                raise ValueError(f"Invalid {name}: {str(e)}")

        def validate_positive_int(value, name):
            try:
                value = int(value)
                if value < 0:
                    raise ValueError(f"{name} must be positive")
                return value
            except (TypeError, ValueError) as e:
                raise ValueError(f"Invalid {name}: {str(e)}")

        # Validate attack type
        valid_attacks = {
            "No Attack", "Label Flipping", "Sample Poisoning", "Model Poisoning",
            "GLL Neuron Inversion", "Swapping Weights", "Delayer", "Flooding"
        }
        
        # Handle attack parameter which can be either a string or a list
        if isinstance(attack, list):
            if not attack:  # Empty list
                attack = "No Attack"
            else:
                attack = attack[0]  # Take the first attack if it's a list
        elif not isinstance(attack, str):
            raise ValueError(f"Invalid attack type: {attack}. Expected string or list.")

        if attack not in valid_attacks:
            raise ValueError(f"Invalid attack type: {attack}")

        # Validate percentage parameters
        poisoned_node_percent = validate_percentage(poisoned_node_percent, "poisoned_node_percent")
        poisoned_sample_percent = validate_percentage(poisoned_sample_percent, "poisoned_sample_percent")
        poisoned_noise_percent = validate_percentage(poisoned_noise_percent, "poisoned_noise_percent")

        nodes_index = []
        # Get the nodes index
        if federation == "DFL":
            nodes_index = list(nodes.keys())
        else:
            for node in nodes:
                if nodes[node]["role"] != "server":
                    nodes_index.append(node)

        logging.info(f"Nodes index: {nodes_index}")
        logging.info(f"Attack type: {attack}")
        logging.info(f"Poisoned node percent: {poisoned_node_percent}")

        mal_nodes_defined = any(nodes[node]["malicious"] for node in nodes)
        logging.info(f"Malicious nodes already defined: {mal_nodes_defined}")

        attacked_nodes = []

        if not mal_nodes_defined and attack != "No Attack":
            n_nodes = len(nodes_index)
            # Number of attacked nodes, round up
            num_attacked = int(math.ceil(poisoned_node_percent / 100 * n_nodes))
            if num_attacked > n_nodes:
                num_attacked = n_nodes

            # Get the index of attacked nodes
            attacked_nodes = random.sample(nodes_index, num_attacked)
            logging.info(f"Number of nodes to attack: {num_attacked}")
            logging.info(f"Attacked nodes: {attacked_nodes}")

        # Assign the role of each node
        for node in nodes:
            node_att = "No Attack"
            malicious = False
            with_reputation = self.with_reputation
            
            if node in attacked_nodes or nodes[node]["malicious"]:
                malicious = True
                with_reputation = False
                node_att = attack
                logging.info(f"Node {node} marked as malicious with attack {attack}")
                
                # Initialize attack parameters with defaults
                attack_params = attack_params.copy() if attack_params else {}
                
                # Set attack-specific parameters
                if attack == "Label Flipping":
                    attack_params["poisonedNodePercent"] = poisoned_node_percent
                    attack_params["poisonedSamplePercent"] = poisoned_sample_percent
                    attack_params["targeted"] = attack_params.get("targeted", False)
                    if attack_params["targeted"]:
                        attack_params["targetLabel"] = validate_positive_int(
                            attack_params.get("targetLabel", 4), "targetLabel"
                        )
                        attack_params["targetChangedLabel"] = validate_positive_int(
                            attack_params.get("targetChangedLabel", 7), "targetChangedLabel"
                        )
                
                elif attack == "Sample Poisoning":
                    attack_params["poisonedNodePercent"] = poisoned_node_percent
                    attack_params["poisonedSamplePercent"] = poisoned_sample_percent
                    attack_params["poisonedNoisePercent"] = poisoned_noise_percent
                    attack_params["noiseType"] = attack_params.get("noiseType", "Salt")
                    attack_params["targeted"] = attack_params.get("targeted", False)
                
                elif attack == "Model Poisoning":
                    attack_params["poisonedNodePercent"] = poisoned_node_percent
                    attack_params["poisonedNoisePercent"] = poisoned_noise_percent
                    attack_params["noiseType"] = attack_params.get("noiseType", "Salt")
                
                elif attack == "GLL Neuron Inversion":
                    attack_params["poisonedNodePercent"] = poisoned_node_percent
                
                elif attack == "Swapping Weights":
                    attack_params["poisonedNodePercent"] = poisoned_node_percent
                    attack_params["layerIdx"] = validate_positive_int(
                        attack_params.get("layerIdx", 0), "layerIdx"
                    )
                
                elif attack == "Delayer":
                    attack_params["poisonedNodePercent"] = poisoned_node_percent
                    attack_params["delay"] = validate_positive_int(
                        attack_params.get("delay", 10), "delay"
                    )
                    attack_params["targetPercentage"] = validate_percentage(
                        attack_params.get("targetPercentage", 100), "targetPercentage"
                    )
                    attack_params["selectionInterval"] = validate_positive_int(
                        attack_params.get("selectionInterval", 1), "selectionInterval"
                    )
                
                elif attack == "Flooding":
                    attack_params["poisonedNodePercent"] = poisoned_node_percent
                    attack_params["floodingFactor"] = validate_positive_int(
                        attack_params.get("floodingFactor", 100), "floodingFactor"
                    )
                    attack_params["targetPercentage"] = validate_percentage(
                        attack_params.get("targetPercentage", 100), "targetPercentage"
                    )
                    attack_params["selectionInterval"] = validate_positive_int(
                        attack_params.get("selectionInterval", 1), "selectionInterval"
                    )
                
                # Add common attack parameters
                attack_params["startRound"] = validate_positive_int(
                    attack_params.get("startRound", 1), "startRound"
                )
                attack_params["stopRound"] = validate_positive_int(
                    attack_params.get("stopRound", 10), "stopRound"
                )
                attack_params["attackInterval"] = validate_positive_int(
                    attack_params.get("attackInterval", 1), "attackInterval"
                )

                # Validate round parameters
                if attack_params["startRound"] >= attack_params["stopRound"]:
                    raise ValueError("startRound must be less than stopRound")

            nodes[node]["malicious"] = malicious
            nodes[node]["with_reputation"] = with_reputation
            nodes[node]["attacks"] = node_att
            nodes[node]["attack_params"] = attack_params

            # Ensure the attack type is properly set in the node configuration
            if malicious and attack != "No Attack":
                nodes[node]["adversarial_args"] = {
                    "attacks": attack,
                    "attack_params": attack_params
                }
            else:
                nodes[node]["adversarial_args"] = {
                    "attacks": "No Attack",
                    "attack_params": {}
                }

            logging.info(f"Node {node} final configuration - malicious: {nodes[node]['malicious']}, attack: {nodes[node]['attacks']}")

        return nodes

    def mobility_assign(self, nodes, mobile_participants_percent):
        """Assign mobility to nodes"""
        import random

        # Number of mobile nodes, round down
        num_mobile = math.floor(mobile_participants_percent / 100 * len(nodes))
        if num_mobile > len(nodes):
            num_mobile = len(nodes)

        # Get the index of mobile nodes
        mobile_nodes = random.sample(list(nodes.keys()), num_mobile)

        # Assign the role of each node
        for node in nodes:
            node_mob = False
            if node in mobile_nodes:
                node_mob = True
            nodes[node]["mobility"] = node_mob
        return nodes

    @classmethod
    def from_dict(cls, data):
        return cls(**data)


# Class to manage the current scenario
class ScenarioManagement:
    def __init__(self, scenario, user=None):
        # Current scenario
        self.scenario = Scenario.from_dict(scenario)
        # Uid of the user
        self.user = user
        # Scenario management settings
        self.start_date_scenario = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.scenario_name = f"nebula_{self.scenario.federation}_{datetime.now().strftime('%d_%m_%Y_%H_%M_%S')}"
        self.root_path = os.environ.get("NEBULA_ROOT_HOST")
        self.host_platform = os.environ.get("NEBULA_HOST_PLATFORM")
        self.config_dir = os.path.join(os.environ.get("NEBULA_CONFIG_DIR"), self.scenario_name)
        self.log_dir = os.environ.get("NEBULA_LOGS_DIR")
        self.cert_dir = os.environ.get("NEBULA_CERTS_DIR")
        self.advanced_analytics = os.environ.get("NEBULA_ADVANCED_ANALYTICS", "False") == "True"
        self.config = Config(entity="scenarioManagement")

        # Assign the controller endpoint
        if self.scenario.deployment == "docker":
            self.controller = f"{os.environ.get('NEBULA_CONTROLLER_NAME')}_nebula-frontend"
        else:
            self.controller = f"127.0.0.1:{os.environ.get('NEBULA_FRONTEND_PORT')}"

        self.topologymanager = None
        self.env_path = None
        self.use_blockchain = self.scenario.agg_algorithm == "BlockchainReputation"

        # Create Scenario management dirs
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(os.path.join(self.log_dir, self.scenario_name), exist_ok=True)
        os.makedirs(self.cert_dir, exist_ok=True)

        # Give permissions to the directories
        os.chmod(self.config_dir, 0o777)
        os.chmod(os.path.join(self.log_dir, self.scenario_name), 0o777)
        os.chmod(self.cert_dir, 0o777)

        # Save the scenario configuration
        scenario_file = os.path.join(self.config_dir, "scenario.json")
        with open(scenario_file, "w") as f:
            json.dump(scenario, f, sort_keys=False, indent=2)

        os.chmod(scenario_file, 0o777)

        # Save management settings
        settings = {
            "scenario_name": self.scenario_name,
            "root_path": self.root_path,
            "config_dir": self.config_dir,
            "log_dir": self.log_dir,
            "cert_dir": self.cert_dir,
            "env": None,
            "use_blockchain": self.use_blockchain,
        }

        settings_file = os.path.join(self.config_dir, "settings.json")
        with open(settings_file, "w") as f:
            json.dump(settings, f, sort_keys=False, indent=2)

        os.chmod(settings_file, 0o777)

        self.scenario.nodes = self.scenario.attack_node_assign(
            self.scenario.nodes,
            self.scenario.federation,
            self.scenario.attacks,
            int(self.scenario.poisoned_node_percent),
            int(self.scenario.poisoned_sample_percent),
            int(self.scenario.poisoned_noise_percent),
            self.scenario.attack_params,
        )

        if self.scenario.mobility:
            mobile_participants_percent = int(self.scenario.mobile_participants_percent)
            self.scenario.nodes = self.scenario.mobility_assign(self.scenario.nodes, mobile_participants_percent)
        else:
            self.scenario.nodes = self.scenario.mobility_assign(self.scenario.nodes, 0)

        # Save node settings
        for node in self.scenario.nodes:
            node_config = self.scenario.nodes[node]
            participant_file = os.path.join(self.config_dir, f"participant_{node_config['id']}.json")
            os.makedirs(os.path.dirname(participant_file), exist_ok=True)
            shutil.copy(
                os.path.join(
                    os.path.dirname(__file__),
                    "./frontend/config/participant.json.example",
                ),
                participant_file,
            )
            os.chmod(participant_file, 0o777)
            with open(participant_file) as f:
                participant_config = json.load(f)

            participant_config["network_args"]["ip"] = node_config["ip"]
            participant_config["network_args"]["port"] = int(node_config["port"])
            participant_config["device_args"]["idx"] = node_config["id"]
            participant_config["device_args"]["start"] = node_config["start"]
            participant_config["device_args"]["role"] = node_config["role"]
            participant_config["device_args"]["proxy"] = node_config["proxy"]
            participant_config["device_args"]["malicious"] = node_config["malicious"]
            participant_config["scenario_args"]["rounds"] = int(self.scenario.rounds)
            participant_config["data_args"]["dataset"] = self.scenario.dataset
            participant_config["data_args"]["iid"] = self.scenario.iid
            participant_config["data_args"]["partition_selection"] = self.scenario.partition_selection
            participant_config["data_args"]["partition_parameter"] = self.scenario.partition_parameter
            participant_config["model_args"]["model"] = self.scenario.model
            participant_config["training_args"]["epochs"] = int(self.scenario.epochs)
            participant_config["device_args"]["accelerator"] = self.scenario.accelerator
            participant_config["device_args"]["gpu_id"] = self.scenario.gpu_id
            participant_config["device_args"]["logging"] = self.scenario.logginglevel
            participant_config["aggregator_args"]["algorithm"] = self.scenario.agg_algorithm
            participant_config["adversarial_args"]["attacks"] = node_config["attacks"]
            participant_config["adversarial_args"]["attack_params"] = node_config["attack_params"]
            participant_config["defense_args"]["with_reputation"] = node_config["with_reputation"]
            # participant_config["defense_args"]["is_dynamic_topology"] = self.scenario.is_dynamic_topology
            # participant_config["defense_args"]["is_dynamic_aggregation"] = self.scenario.is_dynamic_aggregation
            # participant_config["defense_args"]["target_aggregation"] = self.scenario.target_aggregation
            participant_config["defense_args"]["reputation_metrics"] = self.scenario.reputation_metrics
            participant_config["defense_args"]["initial_reputation"] = self.scenario.initial_reputation
            participant_config["defense_args"]["weighting_factor"] = self.scenario.weighting_factor
            participant_config["defense_args"]["weight_model_arrival_latency"] = (
                self.scenario.weight_model_arrival_latency
            )
            participant_config["defense_args"]["weight_model_similarity"] = self.scenario.weight_model_similarity
            participant_config["defense_args"]["weight_num_messages"] = self.scenario.weight_num_messages
            participant_config["defense_args"]["weight_fraction_params_changed"] = (
                self.scenario.weight_fraction_params_changed
            )
            participant_config["mobility_args"]["random_geo"] = self.scenario.random_geo
            participant_config["mobility_args"]["latitude"] = self.scenario.latitude
            participant_config["mobility_args"]["longitude"] = self.scenario.longitude
            participant_config["mobility_args"]["mobility"] = node_config["mobility"]
            participant_config["mobility_args"]["mobility_type"] = self.scenario.mobility_type
            participant_config["mobility_args"]["radius_federation"] = self.scenario.radius_federation
            participant_config["mobility_args"]["scheme_mobility"] = self.scenario.scheme_mobility
            participant_config["mobility_args"]["round_frequency"] = self.scenario.round_frequency
            participant_config["reporter_args"]["report_status_data_queue"] = self.scenario.report_status_data_queue
            participant_config["mobility_args"]["topology_type"] = self.scenario.topology

            with open(participant_file, "w") as f:
                json.dump(participant_config, f, sort_keys=False, indent=2)

    @staticmethod
    def stop_blockchain():
        if sys.platform == "win32":
            try:
                # Comando adaptado para PowerShell en Windows
                command = "docker ps -a --filter 'label=com.docker.compose.project=blockchain' --format '{{.ID}}' | ForEach-Object { docker rm --force --volumes $_ } | Out-Null"
                os.system(f'powershell.exe -Command "{command}"')
            except Exception as e:
                logging.exception(f"Error while killing docker containers: {e}")
        else:
            try:
                process = subprocess.Popen(
                    "docker ps -a --filter 'label=com.docker.compose.project=blockchain' --format '{{.ID}}' | xargs -n 1 docker rm --force --volumes  >/dev/null 2>&1",
                    shell=True,
                )
                process.wait()
            except subprocess.CalledProcessError:
                logging.exception("Docker Compose failed to stop blockchain or blockchain already exited.")

    @staticmethod
    def stop_participants(scenario_name=None):
        # When stopping the nodes, we need to remove the current_scenario_commands.sh file -> it will cause the nodes to stop using PIDs
        try:
            nebula_config_dir = os.environ.get("NEBULA_CONFIG_DIR")
            if not nebula_config_dir:
                current_dir = os.path.dirname(__file__)
                nebula_base_dir = os.path.abspath(os.path.join(current_dir, ".."))
                nebula_config_dir = os.path.join(nebula_base_dir, "app", "config")
                logging.info(f"NEBULA_CONFIG_DIR not found. Using default path: {nebula_config_dir}")

            if scenario_name:
                if os.environ.get("NEBULA_HOST_PLATFORM") == "windows":
                    scenario_commands_file = os.path.join(
                        nebula_config_dir, scenario_name, "current_scenario_commands.ps1"
                    )
                else:
                    scenario_commands_file = os.path.join(
                        nebula_config_dir, scenario_name, "current_scenario_commands.sh"
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
        except Exception as e:
            logging.exception(f"Error while removing current_scenario_commands.sh file: {e}")

    @staticmethod
    def stop_nodes():
        logging.info("Closing NEBULA nodes... Please wait")
        ScenarioManagement.stop_participants()
        ScenarioManagement.stop_blockchain()

    def load_configurations_and_start_nodes(self, additional_participants=None, schema_additional_participants=None):
        logging.info(f"Generating the scenario {self.scenario_name} at {self.start_date_scenario}")

        # Generate CA certificate
        generate_ca_certificate(dir_path=self.cert_dir)

        # Get participants configurations
        participant_files = glob.glob(f"{self.config_dir}/participant_*.json")
        participant_files.sort()
        if len(participant_files) == 0:
            raise ValueError("No participant files found in config folder")

        self.config.set_participants_config(participant_files)
        self.n_nodes = len(participant_files)
        logging.info(f"Number of nodes: {self.n_nodes}")

        self.topologymanager = (
            self.create_topology(matrix=self.scenario.matrix) if self.scenario.matrix else self.create_topology()
        )

        # Update participants configuration
        is_start_node = False
        config_participants = []
        # ap = len(additional_participants) if additional_participants else 0
        additional_nodes = len(additional_participants) if additional_participants else 0
        logging.info(f"######## nodes: {self.n_nodes} + additionals: {additional_nodes} ######")
        for i in range(self.n_nodes):
            with open(f"{self.config_dir}/participant_" + str(i) + ".json") as f:
                participant_config = json.load(f)
            participant_config["scenario_args"]["federation"] = self.scenario.federation
            participant_config["scenario_args"]["n_nodes"] = self.n_nodes + additional_nodes
            participant_config["network_args"]["neighbors"] = self.topologymanager.get_neighbors_string(i)
            participant_config["scenario_args"]["name"] = self.scenario_name
            participant_config["scenario_args"]["start_time"] = self.start_date_scenario
            participant_config["device_args"]["idx"] = i
            participant_config["device_args"]["uid"] = hashlib.sha1(
                (
                    str(participant_config["network_args"]["ip"])
                    + str(participant_config["network_args"]["port"])
                    + str(self.scenario_name)
                ).encode()
            ).hexdigest()
            if participant_config["mobility_args"]["random_geo"]:
                (
                    participant_config["mobility_args"]["latitude"],
                    participant_config["mobility_args"]["longitude"],
                ) = TopologyManager.get_coordinates(random_geo=True)
            else:
                participant_config["mobility_args"]["latitude"] = self.scenario.latitude
                participant_config["mobility_args"]["longitude"] = self.scenario.longitude
            # If not, use the given coordinates in the frontend
            participant_config["tracking_args"]["local_tracking"] = "advanced" if self.advanced_analytics else "basic"
            participant_config["tracking_args"]["log_dir"] = self.log_dir
            participant_config["tracking_args"]["config_dir"] = self.config_dir

            # Generate node certificate
            keyfile_path, certificate_path = generate_certificate(
                dir_path=self.cert_dir,
                node_id=f"participant_{i}",
                ip=participant_config["network_args"]["ip"],
            )

            participant_config["security_args"]["certfile"] = certificate_path
            participant_config["security_args"]["keyfile"] = keyfile_path

            if participant_config["device_args"]["start"]:
                if not is_start_node:
                    is_start_node = True
                else:
                    raise ValueError("Only one node can be start node")
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
        self.topologymanager.update_nodes(config_participants)
        self.topologymanager.draw_graph(path=f"{self.config_dir}/topology.png", plot=False)

        # Include additional participants (if any) as copies of the last participant
        additional_participants_files = []
        if additional_participants:
            last_participant_file = participant_files[-1]
            last_participant_index = len(participant_files)

            for i, additional_participant in enumerate(additional_participants):
                additional_participant_file = f"{self.config_dir}/participant_{last_participant_index + i}.json"
                shutil.copy(last_participant_file, additional_participant_file)

                with open(additional_participant_file) as f:
                    participant_config = json.load(f)

                logging.info(f"Configuration | additional nodes |  participant: {self.n_nodes + i + 1}")
                last_ip = participant_config["network_args"]["ip"]
                logging.info(f"Valores de la ultima ip: ({last_ip})")
                participant_config["scenario_args"]["n_nodes"] = self.n_nodes + additional_nodes  # self.n_nodes + i + 1
                participant_config["device_args"]["idx"] = last_participant_index + i
                participant_config["network_args"]["neighbors"] = ""
                participant_config["network_args"]["ip"] = (
                    participant_config["network_args"]["ip"].rsplit(".", 1)[0]
                    + "."
                    + str(int(participant_config["network_args"]["ip"].rsplit(".", 1)[1]) + i + 1)
                )
                ip = str(participant_config["network_args"]["ip"])
                logging.info(f"El valor almacenado en json es: {ip}")
                participant_config["device_args"]["uid"] = hashlib.sha1(
                    (
                        str(participant_config["network_args"]["ip"])
                        + str(participant_config["network_args"]["port"])
                        + str(self.scenario_name)
                    ).encode()
                ).hexdigest()
                participant_config["mobility_args"]["additional_node"]["status"] = True
                participant_config["mobility_args"]["additional_node"]["round_start"] = additional_participant["round"]

                # used for late creation nodes
                participant_config["mobility_args"]["late_creation"] = True

                with open(additional_participant_file, "w") as f:
                    json.dump(participant_config, f, sort_keys=False, indent=2)

                additional_participants_files.append(additional_participant_file)

        if additional_participants_files:
            self.config.add_participants_config(additional_participants_files)

        # Splitting dataset
        dataset_name = self.scenario.dataset
        dataset = None
        if dataset_name == "MNIST":
            dataset = MNISTDataset(
                num_classes=10,
                partitions_number=self.n_nodes,
                iid=self.scenario.iid,
                partition=self.scenario.partition_selection,
                partition_parameter=self.scenario.partition_parameter,
                seed=42,
                config_dir=self.config_dir,
            )
        elif dataset_name == "FashionMNIST":
            dataset = FashionMNISTDataset(
                num_classes=10,
                partitions_number=self.n_nodes,
                iid=self.scenario.iid,
                partition=self.scenario.partition_selection,
                partition_parameter=self.scenario.partition_parameter,
                seed=42,
                config_dir=self.config_dir,
            )
        elif dataset_name == "EMNIST":
            dataset = EMNISTDataset(
                num_classes=47,
                partitions_number=self.n_nodes,
                iid=self.scenario.iid,
                partition=self.scenario.partition_selection,
                partition_parameter=self.scenario.partition_parameter,
                seed=42,
                config_dir=self.config_dir,
            )
        elif dataset_name == "CIFAR10":
            dataset = CIFAR10Dataset(
                num_classes=10,
                partitions_number=self.n_nodes,
                iid=self.scenario.iid,
                partition=self.scenario.partition_selection,
                partition_parameter=self.scenario.partition_parameter,
                seed=42,
                config_dir=self.config_dir,
            )
        elif dataset_name == "CIFAR100":
            dataset = CIFAR100Dataset(
                num_classes=100,
                partitions_number=self.n_nodes,
                iid=self.scenario.iid,
                partition=self.scenario.partition_selection,
                partition_parameter=self.scenario.partition_parameter,
                seed=42,
                config_dir=self.config_dir,
            )
        else:
            raise ValueError(f"Dataset {dataset_name} not supported")

        logging.info(f"Splitting {dataset_name} dataset...")
        dataset.initialize_dataset()
        logging.info(f"Splitting {dataset_name} dataset... Done")

        if self.scenario.deployment in ["docker", "process", "physical"]:
            if self.use_blockchain:
                self.start_blockchain()
            if self.scenario.deployment == "docker":
                self.start_nodes_docker()
            elif self.scenario.deployment == "physical":
                self.start_nodes_physical()
            elif self.scenario.deployment == "process":
                self.start_nodes_process()
            else:
                raise ValueError(f"Unknown deployment type: {self.scenario.deployment}")
        else:
            logging.info(
                f"Virtualization mode is disabled for scenario '{self.scenario_name}' with {self.n_nodes} nodes. Waiting for nodes to start manually..."
            )

    def create_topology(self, matrix=None):
        import numpy as np

        if self.scenario.topology == "Random":
            # Create network topology using topology manager (random)
            probability = float(self.scenario.random_topology_probability)
            logging.info(
                f"Creating random network topology using erdos_renyi_graph: nodes={self.n_nodes}, probability={probability}"
            )
            topologymanager = TopologyManager(
                scenario_name=self.scenario_name,
                n_nodes=self.n_nodes,
                b_symmetric=True,
                undirected_neighbor_num=3,
            )
            topologymanager.generate_random_topology(probability)
        elif matrix is not None:
            if self.n_nodes > 2:
                topologymanager = TopologyManager(
                    topology=np.array(matrix),
                    scenario_name=self.scenario_name,
                    n_nodes=self.n_nodes,
                    b_symmetric=True,
                    undirected_neighbor_num=self.n_nodes - 1,
                )
            else:
                topologymanager = TopologyManager(
                    topology=np.array(matrix),
                    scenario_name=self.scenario_name,
                    n_nodes=self.n_nodes,
                    b_symmetric=True,
                    undirected_neighbor_num=2,
                )
        elif self.scenario.topology == "Fully":
            # Create a fully connected network
            topologymanager = TopologyManager(
                scenario_name=self.scenario_name,
                n_nodes=self.n_nodes,
                b_symmetric=True,
                undirected_neighbor_num=self.n_nodes - 1,
            )
            topologymanager.generate_topology()
        elif self.scenario.topology == "Ring":
            # Create a partially connected network (ring-structured network)
            topologymanager = TopologyManager(scenario_name=self.scenario_name, n_nodes=self.n_nodes, b_symmetric=True)
            topologymanager.generate_ring_topology(increase_convergence=True)
        elif self.scenario.topology == "Star" and self.scenario.federation == "CFL":
            # Create a centralized network
            topologymanager = TopologyManager(scenario_name=self.scenario_name, n_nodes=self.n_nodes, b_symmetric=True)
            topologymanager.generate_server_topology()
        else:
            raise ValueError(f"Unknown topology type: {self.scenario.topology}")

        # Assign nodes to topology
        nodes_ip_port = []
        self.config.participants.sort(key=lambda x: x["device_args"]["idx"])
        for i, node in enumerate(self.config.participants):
            nodes_ip_port.append((
                node["network_args"]["ip"],
                node["network_args"]["port"],
                "undefined",
            ))

        topologymanager.add_nodes(nodes_ip_port)
        return topologymanager

    def start_blockchain(self):
        BlockchainDeployer(
            config_dir=f"{self.config_dir}/blockchain",
            input_dir="/nebula/nebula/addons/blockchain",
        )
        try:
            logging.info("Blockchain is being deployed")
            subprocess.check_call([
                "docker",
                "compose",
                "-f",
                f"{self.config_dir}/blockchain/blockchain-docker-compose.yml",
                "up",
                "--remove-orphans",
                "--force-recreate",
                "-d",
                "--build",
            ])
        except subprocess.CalledProcessError:
            logging.exception(
                "Docker Compose failed to start Blockchain, please check if Docker Compose is installed (https://docs.docker.com/compose/install/) and Docker Engine is running."
            )
            raise

    def start_nodes_docker(self):
        logging.info("Starting nodes using Docker Compose...")
        logging.info(f"env path: {self.env_path}")

        network_name = f"{os.environ.get('NEBULA_CONTROLLER_NAME')}_{str(self.user).lower()}-nebula-net-scenario"

        # Create the Docker network
        base = DockerUtils.create_docker_network(network_name)

        client = docker.from_env()

        self.config.participants.sort(key=lambda x: x["device_args"]["idx"])
        i = 2
        container_ids = []
        for idx, node in enumerate(self.config.participants):
            image = "nebula-core"
            name = f"{os.environ.get('NEBULA_CONTROLLER_NAME')}_{self.user}-participant{node['device_args']['idx']}"

            if node["device_args"]["accelerator"] == "gpu":
                environment = {"NVIDIA_DISABLE_REQUIRE": True}
                host_config = client.api.create_host_config(
                    binds=[f"{self.root_path}:/nebula", "/var/run/docker.sock:/var/run/docker.sock"],
                    privileged=True,
                    device_requests=[docker.types.DeviceRequest(driver="nvidia", count=-1, capabilities=[["gpu"]])],
                    extra_hosts={"host.docker.internal": "host-gateway"},
                )
            else:
                environment = ""
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
                f"{start_command} && ifconfig && echo '{base}.1 host.docker.internal' >> /etc/hosts && python /nebula/nebula/node.py /nebula/app/config/{self.scenario_name}/participant_{node['device_args']['idx']}.json",
            ]

            if self.use_blockchain:
                networking_config = client.api.create_networking_config({
                    f"{network_name}": client.api.create_endpoint_config(
                        ipv4_address=f"{base}.{i}",
                    ),
                    f"{os.environ.get('NEBULA_CONTROLLER_NAME')}_nebula-net-base": client.api.create_endpoint_config(),
                    "chainnet": client.api.create_endpoint_config(),
                })
            else:
                networking_config = client.api.create_networking_config({
                    f"{network_name}": client.api.create_endpoint_config(
                        ipv4_address=f"{base}.{i}",
                    ),
                    f"{os.environ.get('NEBULA_CONTROLLER_NAME')}_nebula-net-base": client.api.create_endpoint_config(),
                })

            node["tracking_args"]["log_dir"] = "/nebula/app/logs"
            node["tracking_args"]["config_dir"] = f"/nebula/app/config/{self.scenario_name}"
            node["scenario_args"]["controller"] = self.controller
            node["scenario_args"]["deployment"] = self.scenario.deployment
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
                logging.exception(f"Creating container {name}: {e}")

            try:
                client.api.start(container_id)
                container_ids.append(container_id)
            except Exception as e:
                logging.exception(f"Starting participant {name} error: {e}")
            i += 1

    def start_nodes_process(self):
        logging.info("Starting nodes as processes...")
        logging.info(f"env path: {self.env_path}")

        # Include additional config to the participants
        for idx, node in enumerate(self.config.participants):
            node["tracking_args"]["log_dir"] = os.path.join(self.root_path, "app", "logs")
            node["tracking_args"]["config_dir"] = os.path.join(self.root_path, "app", "config", self.scenario_name)
            node["scenario_args"]["controller"] = self.controller
            node["scenario_args"]["deployment"] = self.scenario.deployment
            node["security_args"]["certfile"] = os.path.join(
                self.root_path,
                "app",
                "certs",
                f"participant_{node['device_args']['idx']}_cert.pem",
            )
            node["security_args"]["keyfile"] = os.path.join(
                self.root_path,
                "app",
                "certs",
                f"participant_{node['device_args']['idx']}_key.pem",
            )
            node["security_args"]["cafile"] = os.path.join(self.root_path, "app", "certs", "ca_cert.pem")

            # Write the config file in config directory
            with open(f"{self.config_dir}/participant_{node['device_args']['idx']}.json", "w") as f:
                json.dump(node, f, indent=4)

        try:
            if self.host_platform == "windows":
                commands = """
                $ParentDir = Split-Path -Parent $PSScriptRoot
                $PID_FILE = "$PSScriptRoot\\current_scenario_pids.txt"
                New-Item -Path $PID_FILE -Force -ItemType File

                """
                sorted_participants = sorted(
                    self.config.participants,
                    key=lambda node: node["device_args"]["idx"],
                    reverse=True,
                )
                for node in sorted_participants:
                    if node["device_args"]["start"]:
                        commands += "Start-Sleep -Seconds 10\n"
                    else:
                        commands += "Start-Sleep -Seconds 2\n"

                    commands += f'Write-Host "Running node {node["device_args"]["idx"]}..."\n'
                    commands += f'$OUT_FILE = "{self.root_path}\\app\\logs\\{self.scenario_name}\\participant_{node["device_args"]["idx"]}.out"\n'
                    commands += f'$ERROR_FILE = "{self.root_path}\\app\\logs\\{self.scenario_name}\\participant_{node["device_args"]["idx"]}.err"\n'

                    # Use Start-Process for executing Python in background and capture PID
                    commands += f"""$process = Start-Process -FilePath "python" -ArgumentList "{self.root_path}\\nebula\\node.py {self.root_path}\\app\\config\\{self.scenario_name}\\participant_{node["device_args"]["idx"]}.json" -PassThru -NoNewWindow -RedirectStandardOutput $OUT_FILE -RedirectStandardError $ERROR_FILE
                Add-Content -Path $PID_FILE -Value $process.Id
                """

                commands += 'Write-Host "All nodes started. PIDs stored in $PID_FILE"\n'

                with open(f"/nebula/app/config/{self.scenario_name}/current_scenario_commands.ps1", "w") as f:
                    f.write(commands)
                os.chmod(f"/nebula/app/config/{self.scenario_name}/current_scenario_commands.ps1", 0o755)
            else:
                commands = '#!/bin/bash\n\nPID_FILE="$(dirname "$0")/current_scenario_pids.txt"\n\n> $PID_FILE\n\n'
                sorted_participants = sorted(
                    self.config.participants,
                    key=lambda node: node["device_args"]["idx"],
                    reverse=True,
                )
                for node in sorted_participants:
                    if node["device_args"]["start"]:
                        commands += "sleep 10\n"
                    else:
                        commands += "sleep 2\n"
                    commands += f'echo "Running node {node["device_args"]["idx"]}..."\n'
                    commands += f"OUT_FILE={self.root_path}/app/logs/{self.scenario_name}/participant_{node['device_args']['idx']}.out\n"
                    commands += f"python {self.root_path}/nebula/node.py {self.root_path}/app/config/{self.scenario_name}/participant_{node['device_args']['idx']}.json > $OUT_FILE 2>&1 &\n"
                    commands += "echo $! >> $PID_FILE\n\n"

                commands += 'echo "All nodes started. PIDs stored in $PID_FILE"\n'

                with open(f"/nebula/app/config/{self.scenario_name}/current_scenario_commands.sh", "w") as f:
                    f.write(commands)
                os.chmod(f"/nebula/app/config/{self.scenario_name}/current_scenario_commands.sh", 0o755)

        except Exception as e:
            raise Exception(f"Error starting nodes as processes: {e}")
        
    def start_nodes_physical(self):
        logging.info("Starting nodes as physical devices...")
        logging.info(f"env path: {self.env_path}")

        for idx, node in enumerate(self.config.participants):
            pass

        logging.info("Physical devices deployment is not implemented publicly. Please use docker or process deployment.")

    @classmethod
    def remove_files_by_scenario(cls, scenario_name):
        try:
            shutil.rmtree(FileUtils.check_path(os.environ["NEBULA_CONFIG_DIR"], scenario_name))
        except FileNotFoundError:
            logging.warning("Files not found, nothing to remove")
        except Exception:
            logging.exception("Unknown error while removing files")
            raise
        try:
            shutil.rmtree(FileUtils.check_path(os.environ["NEBULA_LOGS_DIR"], scenario_name))
        except PermissionError:
            # Avoid error if the user does not have enough permissions to remove the tf.events files
            logging.warning("Not enough permissions to remove the files, moving them to tmp folder")
            os.makedirs(
                FileUtils.check_path(os.environ["NEBULA_ROOT"], os.path.join("app", "tmp", scenario_name)),
                exist_ok=True,
            )
            os.chmod(
                FileUtils.check_path(os.environ["NEBULA_ROOT"], os.path.join("app", "tmp", scenario_name)),
                0o777,
            )
            shutil.move(
                FileUtils.check_path(os.environ["NEBULA_LOGS_DIR"], scenario_name),
                FileUtils.check_path(os.environ["NEBULA_ROOT"], os.path.join("app", "tmp", scenario_name)),
            )
        except FileNotFoundError:
            logging.warning("Files not found, nothing to remove")
        except Exception:
            logging.exception("Unknown error while removing files")

            raise

        try:
            nebula_reputation = os.path.join(
                os.environ["NEBULA_LOGS_DIR"], "..", "..", "nebula", "core", "reputation", scenario_name
            )
            logging.info(f"Removing reputation folder {nebula_reputation}")
            logging.info(f"nebula_reputation: {nebula_reputation}")
            if os.path.exists(nebula_reputation):
                shutil.rmtree(nebula_reputation)
                # logging.info(f"Reputation folder {nebula_reputation} removed successfully")
            else:
                logging.info(f"Reputation folder {nebula_reputation} not found")
        except FileNotFoundError:
            logging.warning("Files not found in reputation folder, nothing to remove")
        except Exception:
            logging.exception("Unknown error while removing files from reputation folder")
            raise

    def scenario_finished(self, timeout_seconds):
        client = docker.from_env()
        all_containers = client.containers.list(all=True)
        containers = [container for container in all_containers if self.scenario_name.lower() in container.name.lower()]

        start_time = datetime.now()
        while True:
            all_containers_finished = True
            for container in containers:
                container.reload()
                if container.status != "exited":
                    all_containers_finished = False
                    break
            if all_containers_finished:
                return True

            current_time = datetime.now()
            elapsed_time = current_time - start_time
            if elapsed_time.total_seconds() >= timeout_seconds:
                for container in containers:
                    container.stop()
                return False

            time.sleep(5)

    @classmethod
    def generate_statistics(cls, path):
        try:
            # Define input directories
            input_event_dirs = sorted(glob.glob(os.path.join(path, "metrics/*")))
            if not input_event_dirs:
                return False
            # Generate statistics
            logging.info(f"Generating statistics for scenario {path}")
            # Where to write reduced TB events
            tb_events_output_dir = os.path.join(path, "metrics", "reduced-data")
            csv_out_path = os.path.join(path, "metrics", "reduced-data-as.csv")
            # Whether to abort or overwrite when csv_out_path already exists
            overwrite = False
            reduce_ops = ("mean", "min", "max", "median", "std", "var")

            # Handle duplicate steps
            handle_dup_steps = "keep-first"
            # Strict steps
            strict_steps = False

            events_dict = tbr.load_tb_events(
                input_event_dirs, handle_dup_steps=handle_dup_steps, strict_steps=strict_steps
            )

            # Number of recorded tags. e.g. would be 3 if you recorded loss, MAE and R^2
            n_scalars = len(events_dict)
            n_steps, n_events = list(events_dict.values())[0].shape

            logging.info(f"Loaded {n_events} TensorBoard runs with {n_scalars} scalars and {n_steps} steps each")
            logging.info(f"Events dict keys: {events_dict.keys()}")

            reduced_events = tbr.reduce_events(events_dict, reduce_ops)

            for op in reduce_ops:
                logging.info(f"Writing '{op}' reduction to '{tb_events_output_dir}-{op}'")

            tbr.write_tb_events(reduced_events, tb_events_output_dir, overwrite)

            logging.info(f"Writing results to '{csv_out_path}'")

            tbr.write_data_file(reduced_events, csv_out_path, overwrite)

            logging.info("Reduction complete")

        except Exception as e:
            logging.exception(f"Error generating statistics: {e}")
            return False
