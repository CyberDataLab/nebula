import logging
from datetime import datetime
import hashlib
import math
from collections import defaultdict
from nebula.addons.topologymanager import TopologyManager
from nebula.config.config import Config
from nebula.core.utils.certificate import generate_certificate
from nebula.core.datasets.nebuladataset import NebulaDataset, factory_nebuladataset, factory_dataset_setup

class ScenarioBuilder():
    def __init__(self, federation_id):
        self._scenario_data = None
        self._config_setup = None
        self.logger = logging.getLogger("Federation-Controller")
        self._topology_manager: TopologyManager = None
        self._scenario_name = ""
        self._federation_id = federation_id
        
    @property
    def sd(self):
        """Scenario data dict"""
        return self._scenario_data
    
    @property
    def tm(self):
        """Topology Manager"""
        return self._topology_manager
    
    def get_scenario_name(self):
        return self._scenario_name
    
    def set_scenario_data(self, scenario_data: dict):
        self._scenario_data = scenario_data
        federation_name = self.sd["federation"]
        self._scenario_name = f"nebula_{federation_name}_{datetime.now().strftime('%Y_%m_%d_%H_%M_%S')}"
        
    def set_config_setup(self, setup: dict):
        self._config_setup = setup
        
    def get_federation_nodes(self) -> dict:
        return self.sd["nodes"]
    
    def get_additional_nodes(self):
        return self.sd["additional_participants"]
    
    def get_dataset_name(self) -> str:
         return self.sd["dataset"]
     
    def get_deployment(self) -> str:
        return self.sd["deployment"]
        
    """                                                     ###############################
                                                            #     SCENARIO CONFIG NODE    #
                                                            ###############################
    """        
    def build_general_configuration(self):
        try:
            self.sd["nodes"] = self._configure_nodes_attacks()
            
            if self.sd.get("mobility", None):
                mobile_participants_percent = int(self.sd["mobile_participants_percent"])
                self.sd["nodes"] = self._mobility_assign(self.sd["nodes"], mobile_participants_percent)
            else:
                self.sd["nodes"] = self._mobility_assign(self.sd["nodes"], 0)
        except Exception as e:
            self.logger.info(f"ERROR: {e}")
            
    def _configure_nodes_attacks(self):
        self.logger.info("Configurating node attacks...")
        poisoned_node_percent = self.sd["attack_params"].get("poisoned_node_percent", 0)
        poisoned_sample_percent = self.sd["attack_params"].get("poisoned_sample_percent", 0)
        poisoned_noise_percent = self.sd["attack_params"].get("poisoned_noise_percent", 0)
        
        nodes = self.attack_node_assign(
            self.sd.get("nodes"),
            self.sd.get("federation"),
            int(poisoned_node_percent),
            int(poisoned_sample_percent),
            int(poisoned_noise_percent),
            self.sd.get("attack_params"),
        )
        
        self.logger.info("Configurating node attacks done")
        return nodes
     
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

        self.logger.info(f"Nodes index: {nodes_index}")
        self.logger.info(f"Attack type: {attack}")
        self.logger.info(f"Poisoned node percent: {poisoned_node_percent}")

        mal_nodes_defined = any(nodes[node]["malicious"] for node in nodes)
        self.logger.info(f"Malicious nodes already defined: {mal_nodes_defined}")

        attacked_nodes = []

        if not mal_nodes_defined and attack != "No Attack":
            n_nodes = len(nodes_index)
            # Number of attacked nodes, round up
            num_attacked = int(math.ceil(poisoned_node_percent / 100 * n_nodes))
            if num_attacked > n_nodes:
                num_attacked = n_nodes

            # Get the index of attacked nodes
            attacked_nodes = random.sample(nodes_index, num_attacked)
            self.logger.info(f"Number of nodes to attack: {num_attacked}")
            self.logger.info(f"Attacked nodes: {attacked_nodes}")

        # Assign the role of each node
        for node in nodes:
            node_att = "No Attack"
            malicious = False
            #node_reputation = self.reputation.copy() if self.reputation else None

            if node in attacked_nodes or nodes[node]["malicious"]:
                malicious = True
                node_reputation = None
                node_att = attack
                self.logger.info(f"Node {node} marked as malicious with attack {attack}")

                # Initialize attack parameters with defaults
                node_attack_params = attack_params.copy() if attack_params else {}

                # Set attack-specific parameters
                if attack == "Label Flipping":
                    node_attack_params["poisoned_node_percent"] = poisoned_node_percent
                    node_attack_params["poisoned_sample_percent"] = poisoned_sample_percent
                    node_attack_params["targeted"] = attack_params.get("targeted", False)
                    if node_attack_params["targeted"]:
                        node_attack_params["target_label"] = validate_positive_int(
                            attack_params.get("target_label", 4), "target_label"
                        )
                        node_attack_params["target_changed_label"] = validate_positive_int(
                            attack_params.get("target_changed_label", 7), "target_changed_label"
                        )

                elif attack == "Sample Poisoning":
                    node_attack_params["poisoned_node_percent"] = poisoned_node_percent
                    node_attack_params["poisoned_sample_percent"] = poisoned_sample_percent
                    node_attack_params["poisoned_noise_percent"] = poisoned_noise_percent
                    node_attack_params["noise_type"] = attack_params.get("noise_type", "Gaussian")
                    node_attack_params["targeted"] = attack_params.get("targeted", False)
                    if node_attack_params["targeted"]:
                        node_attack_params["target_label"] = validate_positive_int(
                            attack_params.get("target_label", 4), "target_label"
                        )

                elif attack == "Model Poisoning":
                    node_attack_params["poisoned_node_percent"] = poisoned_node_percent
                    node_attack_params["poisoned_noise_percent"] = poisoned_noise_percent
                    node_attack_params["noise_type"] = attack_params.get("noise_type", "Gaussian")

                elif attack == "GLL Neuron Inversion":
                    node_attack_params["poisoned_node_percent"] = poisoned_node_percent

                elif attack == "Swapping Weights":
                    node_attack_params["poisoned_node_percent"] = poisoned_node_percent
                    node_attack_params["layer_idx"] = validate_positive_int(
                        attack_params.get("layer_idx", 0), "layer_idx"
                    )

                elif attack == "Delayer":
                    node_attack_params["poisoned_node_percent"] = poisoned_node_percent
                    node_attack_params["delay"] = validate_positive_int(attack_params.get("delay", 10), "delay")
                    node_attack_params["target_percentage"] = validate_percentage(
                        attack_params.get("target_percentage", 100), "target_percentage"
                    )
                    node_attack_params["selection_interval"] = validate_positive_int(
                        attack_params.get("selection_interval", 1), "selection_interval"
                    )

                elif attack == "Flooding":
                    node_attack_params["poisoned_node_percent"] = poisoned_node_percent
                    node_attack_params["flooding_factor"] = validate_positive_int(
                        attack_params.get("flooding_factor", 100), "flooding_factor"
                    )
                    node_attack_params["target_percentage"] = validate_percentage(
                        attack_params.get("target_percentage", 100), "target_percentage"
                    )
                    node_attack_params["selection_interval"] = validate_positive_int(
                        attack_params.get("selection_interval", 1), "selection_interval"
                    )

                # Add common attack parameters
                node_attack_params["round_start_attack"] = validate_positive_int(
                    attack_params.get("round_start_attack", 1), "round_start_attack"
                )
                node_attack_params["round_stop_attack"] = validate_positive_int(
                    attack_params.get("round_stop_attack", 10), "round_stop_attack"
                )
                node_attack_params["attack_interval"] = validate_positive_int(
                    attack_params.get("attack_interval", 1), "attack_interval"
                )

                # Validate round parameters
                if node_attack_params["round_start_attack"] >= node_attack_params["round_stop_attack"]:
                    raise ValueError("round_start_attack must be less than round_stop_attack")

                node_attack_params["attacks"] = node_att
                nodes[node]["malicious"] = True
                nodes[node]["attack_params"] = node_attack_params
                nodes[node]["fake_behavior"] = nodes[node]["role"]
                nodes[node]["role"] = "malicious"
            # else:
            #     nodes[node]["attack_params"] = {"attacks": "No Attack"}

            if nodes[node].get("attack_params", None):
                self.logger.info(
                    f"Node {node} final configuration - malicious: {nodes[node]['malicious']}, attack: {nodes[node]['attack_params']['attacks']}"
                )
            else:
                self.logger.info(
                    f"Node {node} final configuration - malicious: {nodes[node]['malicious']}"
                )

        return nodes

    def _mobility_assign(self, nodes, mobile_participants_percent):
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
        
        
    """                                                     ###############################
                                                            #     SCENARIO CONFIG NODE    #
                                                            ###############################
    """

    def build_scenario_config_for_node(self, index, node) -> dict:
        self.logger.info(f"Start building the scenario configuration for participant {index}")

        def recursive_defaultdict():
            return defaultdict(recursive_defaultdict)
        
        def dictify(d):
            if isinstance(d, defaultdict):
                return {k: dictify(v) for k, v in d.items()}
            return d

        participant_config = recursive_defaultdict()

        addons_config = defaultdict()
        #participant_config["addons"] = dict()
        
                                    # General configuration
        participant_config["scenario_args"]["name"] = self._scenario_name
        participant_config["scenario_args"]["start_time"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        participant_config["scenario_args"]["federation_id"] = self._federation_id
        participant_config["deployment_args"]["additional"] = False                           
                                    
        node_config = node #self.sd["nodes"][index]
        participant_config["network_args"]["ip"] = node_config["ip"]
        if self.sd["deployment"] == "physical":
            participant_config["network_args"]["port"] = 8000
        else:
            participant_config["network_args"]["port"] = int(node_config["port"])
            
        participant_config["network_args"]["simulation"] = self.sd["network_simulation"]
        participant_config["device_args"]["idx"] = node_config["id"]
        participant_config["device_args"]["start"] = node_config["start"]
        participant_config["device_args"]["role"] = node_config["role"]
        participant_config["device_args"]["proxy"] = node_config["proxy"]
        participant_config["device_args"]["malicious"] = node_config["malicious"]
        participant_config["scenario_args"]["rounds"] = int(self.sd["rounds"])
        participant_config["scenario_args"]["random_seed"] = 42
        participant_config["federation_args"]["round"] = 0
        participant_config["data_args"]["dataset"] = self.sd["dataset"]
        participant_config["data_args"]["iid"] = self.sd["iid"]
        participant_config["data_args"]["num_workers"] = 0
        participant_config["data_args"]["partition_selection"] = self.sd["partition_selection"]
        participant_config["data_args"]["partition_parameter"] = self.sd["partition_parameter"]
        participant_config["model_args"]["model"] = self.sd["model"]
        participant_config["training_args"]["epochs"] = int(self.sd["epochs"])
        participant_config["training_args"]["trainer"] = "lightning"
        participant_config["device_args"]["accelerator"] = self.sd["accelerator"]
        participant_config["device_args"]["gpu_id"] = self.sd["gpu_id"]
        participant_config["device_args"]["logging"] = self.sd["logginglevel"]
        participant_config["aggregator_args"]["algorithm"] = self.sd["agg_algorithm"]
        participant_config["aggregator_args"]["aggregation_timeout"] = 60
        
        participant_config["message_args"]= self._configure_message_args()
        participant_config["reporter_args"]= self._configure_reporter_args()
        participant_config["forwarder_args"]= self._configure_forwarder_args()
        participant_config["propagator_args"]= self._configure_propagator_args()
        participant_config["misc_args"]= self._configure_misc_args()
        
                                    # Addons configuration
        
        # Trustworthiness
        try:
            if self.sd.get("with_trustworthiness", None):
                addons_config["trustworthiness"] = self._configure_trustworthiness()
        except Exception as e:
            self.logger.info(f"ERROR: Cannot build trustworthiness configuration - {e}")
            
        # Reputation
        try:
            if self.sd.get("reputation", None) and self.sd["reputation"]["enabled"] and not node_config["role"] == "malicious":
                addons_config["reputation"] = self._configure_reputation() 
        except Exception as e:
            self.logger.info(f"ERROR: Cannot build reputation configuration - {e}")
            
        # Network simulation
        try:
            network_args: dict = (self.sd.get("network_args"), None)
            if network_args and isinstance(network_args, dict) and network_args.get("enabled", None):
                addons_config["network_simulation"] = self._configure_network_simulation()
        except Exception as e:
            self.logger.info(f"ERROR: Cannot build network simulation configuration - {e}")

        # Attacks
        try:
            if node_config["role"] == "malicious":
                addons_config["adversarial_args"] = self._configure_malicious_role(node_config)
        except Exception as e:
            self.logger.info(f"ERROR: Cannot build role configuration - {e}")

        # Mobility
        try:
            if self.sd.get("mobility", None):
                addons_config["mobility"] = self._configure_mobility_args()
        except Exception as e:
            self.logger.info(f"ERROR: Cannot build mobility configuration - {e}")
        
        # Situational awareness module
        try:
            if self._situational_awareness_needed():
                addons_config["situational_awareness"] =  self._configure_situational_awareness(index)
        except Exception as e:
            self.logger.info(f"ERROR: Cannot build situational awareness configuration - {e}")

        # Addon addition to the configuration
        participant_config["addons"] = addons_config

        try:
            config = dictify(participant_config)
        except Exception as e:
            self.logger.info(f"ERROR: Translating into dictionary - {e}")    
                       
        return config
    
    def _configure_message_args(self):
        return {
            "max_local_messages": 10000,
            "compression": "zlib"
        }
    
    def _configure_reporter_args(self):
        return {
            "grace_time_reporter": 10,
            "report_frequency": 5,
            "report_status_data_queue": True
        }
    
    def _configure_forwarder_args(self):
        return {
            "forwarder_interval": 1,
            "forward_messages_interval": 0,
            "number_forwarded_messages": 100
        }
    
    def _configure_propagator_args(self):
        return {
            "propagate_interval": 3,
            "propagate_model_interval": 0,
            "propagation_early_stop": 3,
            "history_size": 20
        }
    
    def _configure_misc_args(self):
        return {
            "grace_time_connection": 10,
            "grace_time_start_federation": 10
        }
    
    def _configure_mobility_args(self):
        return {
            "enabled": True,
            "mobility_type": self.sd["mobility_type"],
            "topology_type": self.sd["topology"],
            "radius_federation": self.sd["radius_federation"],
            "scheme_mobility": self.sd["scheme_mobility"],
            "round_frequency": self.sd["round_frequency"],
            "grace_time_mobility": 60,
            "change_geo_interval": 5
        }
    
    def _configure_malicious_role(self, node_config: dict):
        return {
            "fake_behavior": node_config["fake_behavior"],
            "attack_params": node_config["attack_params"]
        }

    def _configure_trustworthiness(self) -> dict:
        trust_config = {
            "robustness_pillar": self.sd["robustness_pillar"],
            "resilience_to_attacks": self.sd["resilience_to_attacks"],
            "algorithm_robustness": self.sd["algorithm_robustness"],
            "client_reliability": self.sd["client_reliability"],
            "privacy_pillar": self.sd["privacy_pillar"],
            "technique": self.sd["technique"],
            "uncertainty": self.sd["uncertainty"],
            "indistinguishability": self.sd["indistinguishability"],
            "fairness_pillar": self.sd["fairness_pillar"],
            "selection_fairness": self.sd["selection_fairness"],
            "performance_fairness": self.sd["performance_fairness"],
            "class_distribution": self.sd["class_distribution"],
            "explainability_pillar": self.sd["explainability_pillar"],
            "interpretability": self.sd["interpretability"],
            "post_hoc_methods": self.sd["post_hoc_methods"],
            "accountability_pillar": self.sd["accountability_pillar"],
            "factsheet_completeness": self.sd["factsheet_completeness"],
            "architectural_soundness_pillar": self.sd["architectural_soundness_pillar"],
            "client_management": self.sd["client_management"],
            "optimization": self.sd["optimization"],
            "sustainability_pillar": self.sd["sustainability_pillar"],
            "energy_source": self.sd["energy_source"],
            "hardware_efficiency": self.sd["hardware_efficiency"],
            "federation_complexity": self.sd["federation_complexity"],
            "scenario": self.sd,
        }
        return trust_config
    
    def _configure_reputation(self) -> dict:
        rep = self.sd.get("reputation")
        rep["adaptive_args"] = True
        return rep

    def _configure_network_simulation(self) -> dict:
        network_parameters = {}
        network_generation =  dict(self.sd["network_args"]).pop("network_type")
        enabled = dict(self.sd["network_args"]).pop("enabled")
        type = dict(self.sd["network_args"]).pop("type")
        addrs = ""
        
        for node in self.sd["nodes"]:
            ip = self.sd["nodes"][node]["ip"]
            port = self.sd["nodes"][node]["port"]
            addrs = addrs + " " + f"{ip}:{port}"
        
        network_configuration = {  
            "interface": "eth0",
            "verbose": False,
            "preset": network_generation,
            "federation": addrs
        }
        
        network_parameters = {
            "enabled": enabled,
            "type": type,
            "network_config": network_configuration
        }
        
        return network_parameters

    def _situational_awareness_needed(self):
        enabled = False
        arrivals_dep = self.sd.get("arrivals_departures_args", None)
        if arrivals_dep:
            enabled = arrivals_dep["enabled"]
        with_sa = self.sd.get("with_sa", None)
        additionals = self.sd.get("additional_participants", None)
        mob = self.sd.get("mobility", None)

        return with_sa or enabled or arrivals_dep or additionals or mob

    def _configure_situational_awareness(self, index) -> dict:
        try:
            scheduled_isolation = self._configure_arrivals_departures(index)
        except Exception as e:
            self.logger.info(f"ERROR: cannot configure arrival departures section - {e}")

        snp = self.sd.get("sar_neighbor_policy", None)
        topology_management = snp if (snp != "") else self.sd["topology"]
        
        situational_awareness_config = {
            "strict_topology": self.sd["strict_topology"],
            "sa_discovery": {
                "candidate_selector": topology_management,
                "model_handler": self.sd["sad_model_handler"],
                "verbose": True,
            },
            "sa_reasoner": {
                "arbitration_policy": self.sd["sar_arbitration_policy"],
                "verbose": True,
                "sar_components": {
                    "sa_network": True, 
                    "sa_training": self.sd["sar_training"]
                },
                "sa_network": {
                    "neighbor_policy": topology_management,
                    "scheduled_isolation" : scheduled_isolation,
                    "verbose": True
                },
                "sa_training": {
                    "training_policy": self.sd["sar_training_policy"], 
                    "verbose": True
                },
            },
        }
        return situational_awareness_config
     
    def _configure_arrivals_departures(self, index) -> dict:
        arrival_dep_section = self.sd.get("arrivals_departures_args", None)
        if not arrival_dep_section or (arrival_dep_section and not self.sd["arrivals_departures_args"]["enabled"]):
            return {"enabled": False}
     
        config = {"enabled": True}
        departures: list = self.sd["arrivals_departures_args"]["departures"]
        index_departure_config: dict = departures[index]
        if index_departure_config["round_start"] != "":
            config["round_start"] = index_departure_config["round_start"]
            config["duration"] = index_departure_config["duration"] if index_departure_config["duration"] != "" else None
        else:
            config = {"enabled": False}

        return config
    
    """                                                     ###############################
                                                            #        PRELOAD CONFIG       #
                                                            ###############################
    """
        
    def build_preload_initial_node_configuration(self, index, participant_config: dict, log_dir, config_dir, cert_dir, advanced_analytics):
        try:
            participant_config["scenario_args"]["federation"] = self.sd["federation"]
            n_nodes = len(self.sd["nodes"].keys())
            n_additionals = len(self.sd["additional_participants"])
            participant_config["scenario_args"]["n_nodes"] = n_nodes + n_additionals
            
            participant_config["network_args"]["neighbors"] = self.tm.get_neighbors_string(index)
            
            participant_config["device_args"]["idx"] = index
            participant_config["device_args"]["uid"] = hashlib.sha1(
                (
                    str(participant_config["network_args"]["ip"])
                    + str(participant_config["network_args"]["port"])
                    + str(participant_config["scenario_args"]["name"])
                ).encode()
            ).hexdigest()
        except Exception as e:
                self.logger.info(f"ERROR while setting up general stuff")
        
        try:
            if participant_config.get("addons", None) and participant_config["addons"].get("mobility", None):
                if participant_config["addons"]["mobility"].get("random_geo", None):
                    (
                        participant_config["addons"]["mobility"]["latitude"],
                        participant_config["addons"]["mobility"]["longitude"],
                    ) = TopologyManager.get_coordinates(random_geo=True)
                else:
                    participant_config["addons"]["mobility"]["latitude"] = self.sd["latitude"]
                    participant_config["addons"]["mobility"]["longitude"] = self.sd["longitude"]
        except Exception as e:
                self.logger.info(f"ERROR while setting up mobility parameters - {e}")
            
        try:
            participant_config["tracking_args"] = {}
            participant_config["security_args"] = {}

            # If not, use the given coordinates in the frontend
            participant_config["tracking_args"]["local_tracking"] = "default"
            participant_config["tracking_args"]["log_dir"] = log_dir
            participant_config["tracking_args"]["config_dir"] = config_dir
            # Generate node certificate
            keyfile_path, certificate_path = generate_certificate(
                dir_path=cert_dir,
                node_id=f"participant_{index}",
                ip=participant_config["network_args"]["ip"],
            )
            participant_config["security_args"]["certfile"] = certificate_path
            participant_config["security_args"]["keyfile"] = keyfile_path
        except Exception as e:
                self.logger.info(f"ERROR while setting up tracking args and certificates")
    
    def build_preload_additional_node_configuration(self, last_participant_index, index, participant_config):
        n_nodes = len(self.sd["nodes"].keys())
        n_additionals = len(self.sd["additional_participants"])
        last_ip = participant_config["network_args"]["ip"]
        participant_config["scenario_args"]["n_nodes"] = n_nodes + n_additionals  # self.n_nodes + i + 1
        participant_config["device_args"]["idx"] = last_participant_index + index
        participant_config["network_args"]["neighbors"] = ""
        participant_config["network_args"]["ip"] = (
            participant_config["network_args"]["ip"].rsplit(".", 1)[0]
            + "."
            + str(int(participant_config["network_args"]["ip"].rsplit(".", 1)[1]) + index + 1)
        )
        participant_config["device_args"]["uid"] = hashlib.sha1(
            (
                str(participant_config["network_args"]["ip"])
                + str(participant_config["network_args"]["port"])
                + str(self._scenario_name)
            ).encode()
        ).hexdigest()
        participant_config["deployment_args"]["additional"] = True
        
        deployment_round = self.sd["additional_participants"][index]["time_start"]
        participant_config["deployment_args"]["deployment_round"] = deployment_round
        
        # used for late creation nodes
    
    """                                                     ###############################
                                                            #       TOPOLOGY MANAGER      #
                                                            ###############################
    """
    
    def create_topology_manager(self, config: Config):
        try:
            self._topology_manager = (
                self._create_topology(config, matrix=self.sd["matrix"]) if self.sd["matrix"] else self._create_topology(config)
            )
        except Exception as e:
            self.logger.info(f"ERROR: cannot create topology manager - {e}")
        
    def _create_topology(self, config: Config, matrix=None):
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

        n_nodes = len(self.sd["nodes"].keys())
        if self.sd["topology"] == "Random":
            # Create network topology using topology manager (random)
            probability = float(self.sd["random_topology_probability"])
            logging.info(
                f"Creating random network topology using erdos_renyi_graph: nodes={n_nodes}, probability={probability}"
            )
            topologymanager = TopologyManager(
                scenario_name=self._scenario_name,
                n_nodes=n_nodes,
                b_symmetric=True,
                undirected_neighbor_num=3,
            )
            topologymanager.generate_random_topology(probability)
        elif matrix is not None:
            if n_nodes > 2:
                topologymanager = TopologyManager(
                    topology=np.array(matrix),
                    scenario_name=self._scenario_name,
                    n_nodes=n_nodes,
                    b_symmetric=True,
                    undirected_neighbor_num=n_nodes - 1,
                )
            else:
                topologymanager = TopologyManager(
                    topology=np.array(matrix),
                    scenario_name=self._scenario_name,
                    n_nodes=n_nodes,
                    b_symmetric=True,
                    undirected_neighbor_num=2,
                )
        elif self.sd["topology"] == "Fully":
            # Create a fully connected network
            topologymanager = TopologyManager(
                scenario_name=self._scenario_name,
                n_nodes=n_nodes,
                b_symmetric=True,
                undirected_neighbor_num=n_nodes - 1,
            )
            topologymanager.generate_topology()
        elif self.sd["topology"] == "Ring":
            # Create a partially connected network (ring-structured network)
            topologymanager = TopologyManager(scenario_name=self._scenario_name, n_nodes=n_nodes, b_symmetric=True)
            topologymanager.generate_ring_topology(increase_convergence=True)
        elif self.sd["topology"] == "Star" and self.sd["federation"] == "CFL":
            # Create a centralized network
            topologymanager = TopologyManager(scenario_name=self._scenario_name, n_nodes=n_nodes, b_symmetric=True)
            topologymanager.generate_server_topology()
        else:
            top = self.sd["topology"]
            raise ValueError(f"Unknown topology type: {top}")

        # Assign nodes to topology
        nodes_ip_port = []
        config.participants.sort(key=lambda x: int(x["device_args"]["idx"]))
        for i, node in enumerate(config.participants):
            nodes_ip_port.append((
                node["network_args"]["ip"],
                node["network_args"]["port"],
                "undefined",
            ))

        topologymanager.add_nodes(nodes_ip_port)
        return topologymanager
    
    def visualize_topology(self, config_participants, path, plot):
        try:
            self.tm.update_nodes(config_participants)
            self.tm.draw_graph(path=path, plot=plot)
        except Exception as e:
            self.logger.info(f"ERROR: cannot visualize topology - {e}")    

    """                                                     ###############################
                                                            #    DATASET CONFIGURATION    #
                                                            ###############################
    """
    
    def configure_dataset(self, config_dir) -> NebulaDataset:
        try:
            dataset_name = self.get_dataset_name()    
            dataset = factory_nebuladataset(
                dataset_name,
                **self._configure_dataset_config(dataset_name, config_dir)                              
            )
        except Exception as e:
            self.logger.info(f"ERROR: cannot configure dataset - {e}")
        return dataset
        
    def _configure_dataset_config(self, dataset_name, config_dir):
        num_classes = factory_dataset_setup(dataset_name)
        n_nodes = len(self.sd["nodes"].keys())
        n_nodes += len(self.sd["additional_participants"])
        return {
            "num_classes": num_classes,
            "partitions_number": n_nodes,
            "iid": self.sd["iid"],
            "partition": self.sd["partition_selection"],
            "partition_parameter": self.sd["partition_parameter"],
            "seed": 42,
            "config_dir": config_dir,
        }