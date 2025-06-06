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
        attack_params,
        reputation,
        random_geo,
        latitude,
        longitude,
        mobility,
        network_simulation,
        mobility_type,
        radius_federation,
        scheme_mobility,
        round_frequency,
        mobile_participants_percent,
        additional_participants,
        schema_additional_participants,
        with_trustworthiness,
        robustness_pillar,
        resilience_to_attacks,
        algorithm_robustness,
        client_reliability,
        privacy_pillar,
        technique,
        uncertainty,
        indistinguishability,
        fairness_pillar,
        selection_fairness,
        performance_fairness,
        class_distribution,
        explainability_pillar,
        interpretability,
        post_hoc_methods,
        accountability_pillar,
        factsheet_completeness,
        architectural_soundness_pillar,
        client_management,
        optimization,
        sustainability_pillar,
        energy_source,
        hardware_efficiency,
        federation_complexity,
        random_topology_probability,
        with_sa,
        strict_topology,
        sad_candidate_selector,
        sad_model_handler,
        sar_arbitration_policy,
        sar_neighbor_policy,
        sar_training,
        sar_training_policy,
    ):
        """
        Initialize a Scenario instance.

        Args:
            scenario_title (str): Title of the scenario.
            scenario_description (str): Description of the scenario.
            deployment (str): Type of deployment.
            federation (str): Type of federation.
            topology (str): Type of topology.
            nodes (dict): Dictionary of nodes.
            nodes_graph (dict): Dictionary of nodes for graph representation.
            n_nodes (int): Number of nodes.
            matrix (list): Adjacency matrix.
            dataset (str): Name of the dataset.
            iid (bool): Whether the data is IID.
            partition_selection (str): Type of partition selection.
            partition_parameter (float): Parameter for partition selection.
            model (str): Name of the model.
            agg_algorithm (str): Aggregation algorithm.
            rounds (int): Number of rounds.
            logginglevel (bool): Whether to log.
            report_status_data_queue (bool): Whether to report status data.
            accelerator (str): Type of accelerator.
            gpu_id (str): ID of the GPU.
            network_subnet (str): Network subnet.
            network_gateway (str): Network gateway.
            epochs (int): Number of epochs.
            attack_params (dict): Dictionary containing attack parameters.
            reputation (dict): Dictionary containing reputation configuration.
            random_geo (bool): Indicator if random geo is used.
            latitude (float): Latitude for mobility.
            longitude (float): Longitude for mobility.
            mobility (bool): Whether mobility is enabled.
            network_simulation (bool): Whether network simulation is enabled.
            mobility_type (str): Type of mobility.
            radius_federation (float): Radius of federation.
            scheme_mobility (str): Scheme of mobility.
            round_frequency (int): Frequency of rounds.
            mobile_participants_percent (float): Percentage of mobile participants.
            additional_participants (list): List of additional participants.
            schema_additional_participants (str): Schema for additional participants.
            random_topology_probability (float): Probability for random topology.
            with_sa (bool): Whether situational awareness is enabled.
            strict_topology (bool): Whether strict topology is enabled.
            sad_candidate_selector (str): Candidate selector for SAD.
            sad_model_handler (str): Model handler for SAD.
            sar_arbitration_policy (str): Arbitration policy for SAR.
            sar_neighbor_policy (str): Neighbor policy for SAR.
            sar_training (bool): Wheter SAR training is enabled.
            sar_training_policy (str): Training policy for SAR.
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
        self.attack_params = attack_params
        self.reputation = reputation
        self.random_geo = random_geo
        self.latitude = latitude
        self.longitude = longitude
        self.mobility = mobility
        self.network_simulation = network_simulation
        self.mobility_type = mobility_type
        self.radius_federation = radius_federation
        self.scheme_mobility = scheme_mobility
        self.round_frequency = round_frequency
        self.mobile_participants_percent = mobile_participants_percent
        self.additional_participants = additional_participants
        self.with_trustworthiness = with_trustworthiness
        self.robustness_pillar = robustness_pillar,
        self.resilience_to_attacks = resilience_to_attacks,
        self.algorithm_robustness = algorithm_robustness,
        self.client_reliability = client_reliability,
        self.privacy_pillar = privacy_pillar,
        self.technique = technique,
        self.uncertainty = uncertainty,
        self.indistinguishability = indistinguishability,
        self.fairness_pillar = fairness_pillar,
        self.selection_fairness = selection_fairness,
        self.performance_fairness = performance_fairness,
        self.class_distribution = class_distribution,
        self.explainability_pillar = explainability_pillar,
        self.interpretability = interpretability,
        self.post_hoc_methods = post_hoc_methods,
        self.accountability_pillar = accountability_pillar,
        self.factsheet_completeness = factsheet_completeness,
        self.architectural_soundness_pillar = architectural_soundness_pillar,
        self.client_management = client_management,
        self.optimization = optimization,
        self.sustainability_pillar = sustainability_pillar,
        self.energy_source = energy_source,
        self.hardware_efficiency = hardware_efficiency,
        self.federation_complexity = federation_complexity,
        self.schema_additional_participants = schema_additional_participants
        self.random_topology_probability = random_topology_probability
        self.with_sa = with_sa
        self.strict_topology = strict_topology
        self.sad_candidate_selector = sad_candidate_selector
        self.sad_model_handler = sad_model_handler
        self.sar_arbitration_policy = sar_arbitration_policy
        self.sar_neighbor_policy = sar_neighbor_policy
        self.sar_training = sar_training
        self.sar_training_policy = sar_training_policy

    def attack_node_assign(
        self,
        nodes,
        federation,
        poisoned_node_percent,
        poisoned_sample_percent,
        poisoned_noise_percent,
        attack_params,
    ):
        """
        Assign and configure attack parameters to nodes within a federated learning network.

        This method:
            - Validates input attack parameters and percentages.
            - Determines which nodes will be marked as malicious based on the specified
              poisoned node percentage and attack type.
            - Assigns attack roles and parameters to selected nodes.
            - Supports multiple attack types such as Label Flipping, Sample Poisoning,
              Model Poisoning, GLL Neuron Inversion, Swapping Weights, Delayer, and Flooding.
            - Ensures proper validation and setting of attack-specific parameters, including
              targeting, noise types, delays, intervals, and attack rounds.
            - Updates nodes' malicious status, reputation, and attack parameters accordingly.

        Args:
            nodes (dict): Dictionary of nodes with their current attributes.
            federation (str): Type of federated learning framework (e.g., "DFL").
            poisoned_node_percent (float): Percentage of nodes to be poisoned (0-100).
            poisoned_sample_percent (float): Percentage of samples to be poisoned (0-100).
            poisoned_noise_percent (float): Percentage of noise to apply in poisoning (0-100).
            attack_params (dict): Dictionary containing attack type and associated parameters.

        Returns:
            dict: Updated nodes dictionary with assigned malicious roles and attack parameters.

        Raises:
            ValueError: If any input parameter is invalid or attack type is unrecognized.
        """
        import logging
        import math
        import random

        # Validate input parameters
        def validate_percentage(value, name):
            """
            Validate that a given value is a float percentage between 0 and 100.

            Args:
                value: The value to validate, expected to be convertible to float.
                name (str): Name of the parameter, used for error messages.

            Returns:
                float: The validated percentage value.

            Raises:
                ValueError: If the value is not a float or not within the range [0, 100].
            """
            try:
                value = float(value)
                if not 0 <= value <= 100:
                    raise ValueError(f"{name} must be between 0 and 100")
                return value
            except (TypeError, ValueError) as e:
                raise ValueError(f"Invalid {name}: {e!s}")

        def validate_positive_int(value, name):
            """
            Validate that a given value is a positive integer (including zero).

            Args:
                value: The value to validate, expected to be convertible to int.
                name (str): Name of the parameter, used for error messages.

            Returns:
                int: The validated positive integer value.

            Raises:
                ValueError: If the value is not an integer or is negative.
            """
            try:
                value = int(value)
                if value < 0:
                    raise ValueError(f"{name} must be positive")
                return value
            except (TypeError, ValueError) as e:
                raise ValueError(f"Invalid {name}: {e!s}")

        # Validate attack type
        valid_attacks = {
            "No Attack",
            "Label Flipping",
            "Sample Poisoning",
            "Model Poisoning",
            "GLL Neuron Inversion",
            "Swapping Weights",
            "Delayer",
            "Flooding",
        }

        # Get attack type from attack_params
        if attack_params and "attacks" in attack_params:
            attack = attack_params["attacks"]

        # Handle attack parameter which can be either a string or None
        if attack is None:
            attack = "No Attack"
        elif not isinstance(attack, str):
            raise ValueError(f"Invalid attack type: {attack}. Expected string or None.")

        if attack not in valid_attacks:
            raise ValueError(f"Invalid attack type: {attack}. Must be one of {valid_attacks}")

        # Get attack parameters from attack_params
        poisoned_node_percent = attack_params.get("poisoned_node_percent", poisoned_node_percent)
        poisoned_sample_percent = attack_params.get("poisoned_sample_percent", poisoned_sample_percent)
        poisoned_noise_percent = attack_params.get("poisoned_noise_percent", poisoned_noise_percent)

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
            node_reputation = self.reputation.copy() if self.reputation else None

            if node in attacked_nodes or nodes[node]["malicious"]:
                malicious = True
                node_reputation = None
                node_att = attack
                logging.info(f"Node {node} marked as malicious with attack {attack}")

                # Initialize attack parameters with defaults
                node_attack_params = attack_params.copy() if attack_params else {}

                # Set attack-specific parameters
                if attack == "Label Flipping":
                    node_attack_params["poisoned_node_percent"] = poisoned_node_percent
                    node_attack_params["poisoned_sample_percent"] = poisoned_sample_percent
                    node_attack_params["targeted"] = attack_params.get("targeted", False)
                    if node_attack_params["targeted"]:
                        node_attack_params["target_label"] = validate_positive_int(
                            attack_params.get("targetLabel", 4), "target_label"
                        )
                        node_attack_params["target_changed_label"] = validate_positive_int(
                            attack_params.get("targetChangedLabel", 7), "target_changed_label"
                        )

                elif attack == "Sample Poisoning":
                    node_attack_params["poisoned_node_percent"] = poisoned_node_percent
                    node_attack_params["poisoned_sample_percent"] = poisoned_sample_percent
                    node_attack_params["poisoned_noise_percent"] = poisoned_noise_percent
                    node_attack_params["noise_type"] = attack_params.get("noiseType", "Gaussian")
                    node_attack_params["targeted"] = attack_params.get("targeted", False)
                    if node_attack_params["targeted"]:
                        node_attack_params["target_label"] = validate_positive_int(
                            attack_params.get("targetLabel", 4), "target_label"
                        )

                elif attack == "Model Poisoning":
                    node_attack_params["poisoned_node_percent"] = poisoned_node_percent
                    node_attack_params["poisoned_noise_percent"] = poisoned_noise_percent
                    node_attack_params["noise_type"] = attack_params.get("noiseType", "Gaussian")

                elif attack == "GLL Neuron Inversion":
                    node_attack_params["poisoned_node_percent"] = poisoned_node_percent

                elif attack == "Swapping Weights":
                    node_attack_params["poisoned_node_percent"] = poisoned_node_percent
                    node_attack_params["layer_idx"] = validate_positive_int(
                        attack_params.get("layerIdx", 0), "layer_idx"
                    )

                elif attack == "Delayer":
                    node_attack_params["poisoned_node_percent"] = poisoned_node_percent
                    node_attack_params["delay"] = validate_positive_int(attack_params.get("delay", 10), "delay")
                    node_attack_params["target_percentage"] = validate_percentage(
                        attack_params.get("targetPercentage", 100), "target_percentage"
                    )
                    node_attack_params["selection_interval"] = validate_positive_int(
                        attack_params.get("selectionInterval", 1), "selection_interval"
                    )

                elif attack == "Flooding":
                    node_attack_params["poisoned_node_percent"] = poisoned_node_percent
                    node_attack_params["flooding_factor"] = validate_positive_int(
                        attack_params.get("floodingFactor", 100), "flooding_factor"
                    )
                    node_attack_params["target_percentage"] = validate_percentage(
                        attack_params.get("targetPercentage", 100), "target_percentage"
                    )
                    node_attack_params["selection_interval"] = validate_positive_int(
                        attack_params.get("selectionInterval", 1), "selection_interval"
                    )

                # Add common attack parameters
                node_attack_params["round_start_attack"] = validate_positive_int(
                    attack_params.get("roundStartAttack", 1), "round_start_attack"
                )
                node_attack_params["round_stop_attack"] = validate_positive_int(
                    attack_params.get("roundStopAttack", 10), "round_stop_attack"
                )
                node_attack_params["attack_interval"] = validate_positive_int(
                    attack_params.get("attackInterval", 1), "attack_interval"
                )

                # Validate round parameters
                if node_attack_params["round_start_attack"] >= node_attack_params["round_stop_attack"]:
                    raise ValueError("round_start_attack must be less than round_stop_attack")

                node_attack_params["attacks"] = node_att
                nodes[node]["attack_params"] = node_attack_params
            else:
                nodes[node]["attack_params"] = {"attacks": "No Attack"}

            nodes[node]["malicious"] = malicious
            nodes[node]["reputation"] = node_reputation

            logging.info(
                f"Node {node} final configuration - malicious: {nodes[node]['malicious']}, attack: {nodes[node]['attack_params']['attacks']}"
            )

        return nodes

    def mobility_assign(self, nodes, mobile_participants_percent):
        """
        Assign mobility status to a subset of nodes based on a specified percentage.

        This method:
            - Calculates the number of mobile nodes by applying the given percentage.
            - Randomly selects nodes to be marked as mobile.
            - Updates each node's "mobility" attribute to True or False accordingly.

        Args:
            nodes (dict): Dictionary of nodes with their current attributes.
            mobile_participants_percent (float): Percentage of nodes to be assigned mobility (0-100).

        Returns:
            dict: Updated nodes dictionary with mobility status assigned.
        """
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
        """
        Create an instance of the class from a dictionary of attributes.

        This class method:
            - Copies the input dictionary to prevent modification of the original data.
            - Instantiates the class using the dictionary unpacked as keyword arguments.

        Args:
            data (dict): Dictionary containing attributes to initialize the class instance.

        Returns:
            cls: An instance of the class initialized with the provided data.
        """
        # Create a copy of the data to avoid modifying the original
        scenario_data = data.copy()

        # Create the scenario object
        scenario = cls(**scenario_data)

        return scenario


# Class to manage the current scenario
class ScenarioManagement:
    """
    Initialize the scenario management.

    Args:
        scenario (dict): Dictionary containing the scenario configuration.
        user (str, optional): User identifier. Defaults to None.

    Functionality:
    - Loads the scenario from a dictionary.
    - Sets up names and paths for configuration and log storage.
    - Creates necessary directories with proper permissions.
    - Saves the scenario configuration and management settings as JSON files.
    - Assigns malicious and mobile nodes according to scenario parameters.
    - Configures each node individually with parameters for networking, device,
      attacks, defense, mobility, reporting, trustworthiness, and situational awareness.
    """
    def __init__(self, scenario, user=None):
        # Current scenario
        self.scenario = Scenario.from_dict(scenario)
        # Uid of the user
        self.user = user
        # Scenario management settings
        self.start_date_scenario = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self.scenario_name = f"nebula_{self.scenario.federation}_{datetime.now().strftime('%Y_%m_%d_%H_%M_%S')}"
        self.root_path = os.environ.get("NEBULA_ROOT_HOST")
        self.host_platform = os.environ.get("NEBULA_HOST_PLATFORM")
        self.config_dir = os.path.join(os.environ.get("NEBULA_CONFIG_DIR"), self.scenario_name)
        self.log_dir = os.environ.get("NEBULA_LOGS_DIR")
        self.cert_dir = os.environ.get("NEBULA_CERTS_DIR")
        self.advanced_analytics = os.environ.get("NEBULA_ADVANCED_ANALYTICS", "False") == "True"
        self.config = Config(entity="scenarioManagement")

        # Assign the controller endpoint
        if self.scenario.deployment == "docker":
            self.controller = f"{os.environ.get('NEBULA_CONTROLLER_HOST')}:{os.environ.get('NEBULA_CONTROLLER_PORT')}"
        else:
            self.controller = f"127.0.0.1:{os.environ.get('NEBULA_CONTROLLER_PORT')}"

        self.topologymanager = None
        self.env_path = None

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
        }

        settings_file = os.path.join(self.config_dir, "settings.json")
        with open(settings_file, "w") as f:
            json.dump(settings, f, sort_keys=False, indent=2)

        os.chmod(settings_file, 0o777)

        # Get attack parameters from attack_params
        poisoned_node_percent = self.scenario.attack_params.get("poisoned_node_percent", 0)
        poisoned_sample_percent = self.scenario.attack_params.get("poisoned_sample_percent", 0)
        poisoned_noise_percent = self.scenario.attack_params.get("poisoned_noise_percent", 0)

        self.scenario.nodes = self.scenario.attack_node_assign(
            self.scenario.nodes,
            self.scenario.federation,
            int(poisoned_node_percent),
            int(poisoned_sample_percent),
            int(poisoned_noise_percent),
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
                    "../frontend/config/participant.json.example",
                ),
                participant_file,
            )
            os.chmod(participant_file, 0o777)
            with open(participant_file) as f:
                participant_config = json.load(f)

            participant_config["network_args"]["ip"] = node_config["ip"]
            participant_config["network_args"]["port"] = int(node_config["port"])
            participant_config["network_args"]["simulation"] = self.scenario.network_simulation
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
            # To be sure that benign nodes have no attack parameters
            if node_config["malicious"]:
                participant_config["adversarial_args"]["attack_params"] = node_config["attack_params"]
            else:
                participant_config["adversarial_args"]["attack_params"] = {"attacks": "No Attack"}
            participant_config["defense_args"]["reputation"] = self.scenario.reputation

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
            if self.scenario.with_sa:
                participant_config["situational_awareness"] = {
                    "strict_topology": self.scenario.strict_topology,
                    "sa_discovery": {
                        "candidate_selector": self.scenario.sad_candidate_selector,
                        "model_handler": self.scenario.sad_model_handler,
                        "verbose": True,
                    },
                    "sa_reasoner": {
                        "arbitration_policy": self.scenario.sar_arbitration_policy,
                        "verbose": True,
                        "sar_components": {"sa_network": True, "sa_training": self.scenario.sar_training},
                        "sa_network": {"neighbor_policy": self.scenario.sar_neighbor_policy, "verbose": True},
                        "sa_training": {"training_policy": self.scenario.sar_training_policy, "verbose": True},
                    },
                }
            participant_config["trustworthiness"] = self.scenario.with_trustworthiness
            if self.scenario.with_trustworthiness:            
                participant_config["trust_args"] = {
                    "robustness_pillar": self.scenario.robustness_pillar,
                    "resilience_to_attacks": self.scenario.resilience_to_attacks,
                    "algorithm_robustness": self.scenario.algorithm_robustness,
                    "client_reliability": self.scenario.client_reliability,
                    "privacy_pillar": self.scenario.privacy_pillar,
                    "technique": self.scenario.technique,
                    "uncertainty": self.scenario.uncertainty,
                    "indistinguishability": self.scenario.indistinguishability,
                    "fairness_pillar": self.scenario.fairness_pillar,
                    "selection_fairness": self.scenario.selection_fairness,
                    "performance_fairness": self.scenario.performance_fairness,
                    "class_distribution": self.scenario.class_distribution,
                    "explainability_pillar": self.scenario.explainability_pillar,
                    "interpretability": self.scenario.interpretability,
                    "post_hoc_methods": self.scenario.post_hoc_methods,
                    "accountability_pillar":self.scenario.accountability_pillar,
                    "factsheet_completeness": self.scenario.factsheet_completeness,
                    "architectural_soundness_pillar":self.scenario.architectural_soundness_pillar,
                    "client_management": self.scenario.client_management,
                    "optimization": self.scenario.optimization,
                    "sustainability_pillar": self.scenario.sustainability_pillar,
                    "energy_source": self.scenario.energy_source,
                    "hardware_efficiency": self.scenario.hardware_efficiency,
                    "federation_complexity": self.scenario.federation_complexity,
                    "scenario": scenario
                }

            with open(participant_file, "w") as f:
                json.dump(participant_config, f, sort_keys=False, indent=2)

    @staticmethod
    def stop_participants(scenario_name=None):
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
        # When stopping the nodes, we need to remove the current_scenario_commands.sh file -> it will cause the nodes to stop using PIDs
        try:
            nebula_config_dir = os.environ.get("NEBULA_CONFIG_DIR")
            if not nebula_config_dir:
                current_dir = os.path.dirname(__file__)
                nebula_base_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))
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
        """
        Stop all running NEBULA nodes.
    
        This method logs the shutdown action and calls the stop_participants
        method to remove all scenario command files, which signals nodes to stop.
        """
        logging.info("Closing NEBULA nodes... Please wait")
        ScenarioManagement.stop_participants()

    def load_configurations_and_start_nodes(self, additional_participants=None, schema_additional_participants=None):
        """
        Load participant configurations, generate certificates, setup topology, split datasets, 
        and start nodes according to the scenario deployment type.

        This method:
        - Generates CA and node certificates.
        - Loads and updates participant configuration files.
        - Creates the network topology and updates participant roles.
        - Handles additional participants if provided.
        - Initializes and partitions the dataset based on the scenario.
        - Starts nodes using the specified deployment method (docker, physical, or process).

        Args:
            additional_participants (list, optional): List of additional participant configurations to add.
            schema_additional_participants (optional): Schema for additional participants (currently unused).

        Raises:
            ValueError: If no participant files found, multiple start nodes detected, no start node found,
                        unsupported dataset or unknown deployment type.
        """
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
        """
        Create and return a network topology manager based on the scenario's topology settings or a given adjacency matrix.

        Supports multiple topology types:
        - Random: Generates an Erdős-Rényi random graph with specified connection probability.
        - Matrix: Uses a provided adjacency matrix to define the topology.
        - Fully: Creates a fully connected network.
        - Ring: Creates a ring-structured network with partial connectivity.
        - Star: Creates a centralized star topology (only for CFL federation).

        The method assigns IP and port information to nodes and returns the configured TopologyManager instance.

        Args:
            matrix (optional): Adjacency matrix to define custom topology. If provided, overrides scenario topology.

        Raises:
            ValueError: If an unknown topology type is specified in the scenario.

        Returns:
            TopologyManager: Configured topology manager with nodes assigned.
        """
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

    def start_nodes_docker(self):
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
                environment = {"NVIDIA_DISABLE_REQUIRE": True, "NEBULA_LOGS_DIR": "/nebula/app/logs/", "NEBULA_CONFIG_DIR": "/nebula/app/config/"}
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
        """
        Starts participant nodes as independent background processes on the host machine.

        This method performs the following steps:
        - Updates each participant's configuration with paths for logs, config, certificates,
          and scenario parameters.
        - Writes the updated configuration for each participant to a JSON file.
        - Generates and writes a platform-specific script to start all participant nodes:
            - On Windows, it creates a PowerShell script that launches each node as a background
              process, redirects output and error streams to log files, and records process IDs.
            - On Unix-like systems, it creates a bash script that launches each node in the
              background, redirects output, and stores PIDs in a file.
        - Sets executable permissions for the generated script.

        Raises:
            Exception: If any error occurs during the script generation or file operations.

        Notes:
            - The generated script must be executed separately by the user to actually start the nodes.
            - Sleep intervals are added before starting nodes depending on their 'start' flag.
            - Logs and PIDs are stored under the configured directories for monitoring and management.
        """
        self.processes_root_path = os.path.join(os.path.dirname(__file__), "..", "..")
        logging.info("Starting nodes as processes...")
        logging.info(f"env path: {self.env_path}")

        # Include additional config to the participants
        for idx, node in enumerate(self.config.participants):
            node["tracking_args"]["log_dir"] = os.path.join(self.root_path, "app", "logs")
            node["tracking_args"]["config_dir"] = os.path.join(self.root_path, "app", "config", self.scenario_name)
            node["scenario_args"]["controller"] = self.controller
            node["scenario_args"]["deployment"] = self.scenario.deployment
            node["security_args"]["certfile"] = os.path.join(self.root_path, "app", "certs", f"participant_{node['device_args']['idx']}_cert.pem")
            node["security_args"]["keyfile"] = os.path.join(self.root_path, "app", "certs", f"participant_{node['device_args']['idx']}_key.pem")
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
                    commands += f"""$process = Start-Process -FilePath "python" -ArgumentList "{self.root_path}\\nebula\\core\\node.py {self.root_path}\\app\\config\\{self.scenario_name}\\participant_{node["device_args"]["idx"]}.json" -PassThru -NoNewWindow -RedirectStandardOutput $OUT_FILE -RedirectStandardError $ERROR_FILE
                Add-Content -Path $PID_FILE -Value $process.Id
                """

                commands += 'Write-Host "All nodes started. PIDs stored in $PID_FILE"\n'

                with open(f"{self.config_dir}/current_scenario_commands.ps1", "w") as f:
                    f.write(commands)
                os.chmod(f"{self.config_dir}/current_scenario_commands.ps1", 0o755)
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
                    commands += f"python {self.root_path}/nebula/core/node.py {self.root_path}/app/config/{self.scenario_name}/participant_{node['device_args']['idx']}.json &\n"
                    commands += "echo $! >> $PID_FILE\n\n"

                commands += 'echo "All nodes started. PIDs stored in $PID_FILE"\n'

                with open(f"{self.config_dir}/current_scenario_commands.sh", "w") as f:
                    f.write(commands)
                os.chmod(f"{self.config_dir}/current_scenario_commands.sh", 0o755)

        except Exception as e:
            raise Exception(f"Error starting nodes as processes: {e}")

    def start_nodes_physical(self):
        """
        Placeholder method for starting nodes on physical devices.

        Logs informational messages indicating that deployment on physical devices
        is not implemented or supported publicly. Users are encouraged to use Docker
        or process-based deployment methods instead.

        Currently, this method does not perform any actions.
        """
        logging.info("Starting nodes as physical devices...")
        logging.info(f"env path: {self.env_path}")

        for idx, node in enumerate(self.config.participants):
            pass

        logging.info(
            "Physical devices deployment is not implemented publicly. Please use docker or process deployment."
        )

    @classmethod
    def remove_files_by_scenario(cls, scenario_name):
        """
        Remove configuration, logs, and reputation files associated with a given scenario.

        This method attempts to delete the directories related to the specified scenario
        within the NEBULA_CONFIG_DIR and NEBULA_LOGS_DIR environment paths, as well as
        the reputation folder inside the nebula core directory.

        If files or directories are not found, a warning is logged but the method continues.
        If a PermissionError occurs while removing log files, the files are moved to a temporary
        folder inside the NEBULA_ROOT path to avoid permission issues.

        Raises:
            Exception: Re-raises any unexpected exceptions encountered during file operations.
        """
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
            if os.path.exists(nebula_reputation):
                shutil.rmtree(nebula_reputation)
                logging.info(f"Reputation folder {nebula_reputation} removed successfully")
        except FileNotFoundError:
            logging.warning("Files not found in reputation folder, nothing to remove")
        except Exception:
            logging.exception("Unknown error while removing files from reputation folder")
            raise

    def scenario_finished(self, timeout_seconds):
        """
        Check if all Docker containers related to the current scenario have finished.

        This method monitors the Docker containers whose names contain the scenario name.
        It waits until all such containers have exited or until the specified timeout is reached.
        If the timeout is exceeded, all running scenario containers are stopped.

        Args:
            timeout_seconds (int): Maximum number of seconds to wait for containers to finish.

        Returns:
            bool: True if all containers finished before the timeout, False if timeout was reached and containers were stopped.
        """
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
        """
        Generate reduced statistical summaries from TensorBoard event files in a scenario directory.
    
        This method loads TensorBoard event data from the specified directory,
        performs statistical reductions (mean, min, max, median, std, var) over scalar metrics,
        and writes the reduced data back both as TensorBoard event files and as a CSV summary.
    
        Args:
            path (str): The root directory containing a 'metrics' subdirectory with TensorBoard event files.
    
        Returns:
            bool: True if statistics were generated successfully, False if no input event directories
                  were found or if an error occurred during processing.
        """
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
