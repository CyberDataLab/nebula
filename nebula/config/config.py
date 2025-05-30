import json
import logging
import os
from logging import FileHandler, Formatter

CYAN = "\x1b[0;36m"
RESET = "\x1b[0m"

TRAINING_LOGGER = "nebula.training"


class Config:
    topology = {}
    participant = {}

    participants = []  # Configuration of each participant (this information is stored only in the controller)
    participants_path = []

    def __init__(self, entity, topology_config_file=None, participant_config_file=None):
        self.entity = entity

        if topology_config_file is not None:
            self.set_topology_config(topology_config_file)

        if participant_config_file is not None:
            self.set_participant_config(participant_config_file)

        if self.participant != {}:
            self.__default_config()
            self.__set_default_logging()
            self.__set_training_logging()

    def __getstate__(self):
        # Return the attributes of the class that should be serialized
        return {"topology": self.topology, "participant": self.participant}

    def __setstate__(self, state):
        # Set the attributes of the class from the serialized state
        self.topology = state["topology"]
        self.participant = state["participant"]

    def get_topology_config(self):
        return json.dumps(self.topology, indent=2)

    def get_participant_config(self):
        return json.dumps(self.participant, indent=2)

    def get_train_logging_config(self):
        # TBD
        pass

    def __default_config(self):
        self.participant["device_args"]["name"] = (
            f"participant_{self.participant['device_args']['idx']}_{self.participant['network_args']['ip']}_{self.participant['network_args']['port']}"
        )
        self.participant["network_args"]["addr"] = (
            f"{self.participant['network_args']['ip']}:{self.participant['network_args']['port']}"
        )

    def __set_default_logging(self):
        experiment_name = self.participant["scenario_args"]["name"]
        self.log_dir = os.path.join(self.participant["tracking_args"]["log_dir"], experiment_name)
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
        self.log_filename = f"{self.log_dir}/participant_{self.participant['device_args']['idx']}"
        os.makedirs(os.path.dirname(self.log_filename), exist_ok=True)
        (
            console_handler,
            file_handler,
            file_handler_only_debug,
            exp_errors_file_handler,
        ) = self.__setup_logging(self.log_filename)

        level = logging.DEBUG if self.participant["device_args"]["logging"] else logging.CRITICAL
        logging.basicConfig(
            level=level,
            handlers=[
                console_handler,
                file_handler,
                file_handler_only_debug,
                exp_errors_file_handler,
            ],
        )

    def __setup_logging(self, log_filename):
        info_file_format = (
            f"%(asctime)s - {self.participant['device_args']['name']} - [%(filename)s:%(lineno)d] %(message)s"
        )
        debug_file_format = f"%(asctime)s - {self.participant['device_args']['name']} - [%(filename)s:%(lineno)d] %(message)s\n[in %(pathname)s:%(lineno)d]"
        log_console_format = f"{CYAN}%(asctime)s - {self.participant['device_args']['name']} - [%(filename)s:%(lineno)d]{RESET}\n%(message)s"

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.CRITICAL)
        console_handler.setFormatter(Formatter(log_console_format))

        file_handler = FileHandler(f"{log_filename}.log", mode="w", encoding="utf-8")
        file_handler.setLevel(logging.INFO if self.participant["device_args"]["logging"] else logging.CRITICAL)
        file_handler.setFormatter(Formatter(info_file_format))

        file_handler_only_debug = FileHandler(f"{log_filename}_debug.log", mode="w", encoding="utf-8")
        file_handler_only_debug.setLevel(
            logging.DEBUG if self.participant["device_args"]["logging"] else logging.CRITICAL
        )
        file_handler_only_debug.addFilter(lambda record: record.levelno == logging.DEBUG)
        file_handler_only_debug.setFormatter(Formatter(debug_file_format))

        exp_errors_file_handler = FileHandler(f"{log_filename}_error.log", mode="w", encoding="utf-8")
        exp_errors_file_handler.setLevel(
            logging.WARNING if self.participant["device_args"]["logging"] else logging.CRITICAL
        )
        exp_errors_file_handler.setFormatter(Formatter(debug_file_format))

        return (
            console_handler,
            file_handler,
            file_handler_only_debug,
            exp_errors_file_handler,
        )

    def __set_training_logging(self):
        training_log_filename = f"{self.log_filename}_training"
        info_file_format = (
            f"%(asctime)s - {self.participant['device_args']['name']} - [%(filename)s:%(lineno)d] %(message)s"
        )
        log_console_format = f"{CYAN}%(asctime)s - {self.participant['device_args']['name']} - [%(filename)s:%(lineno)d]{RESET}\n%(message)s"
        level = logging.DEBUG if self.participant["device_args"]["logging"] else logging.CRITICAL

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.CRITICAL)
        console_handler.setFormatter(Formatter(log_console_format))

        file_handler = FileHandler(f"{training_log_filename}.log", mode="w", encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(Formatter(info_file_format))

        logger = logging.getLogger(TRAINING_LOGGER)
        logger.setLevel(level)
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)
        logger.propagate = False

        pl_logger = logging.getLogger("lightning.pytorch")
        pl_logger.setLevel(logging.INFO)
        pl_logger.handlers = []
        pl_logger.propagate = False
        pl_logger.addHandler(console_handler)
        pl_logger.addHandler(file_handler)

    def to_json(self):
        # Return participant configuration as a json string
        return json.dumps(self.participant, sort_keys=False, indent=2)

    # Read the configuration file scenario_config.json, and return a dictionary with the configuration
    def set_participant_config(self, participant_config):
        with open(participant_config) as json_file:
            self.participant = json.load(json_file)

    def set_topology_config(self, topology_config_file):
        with open(topology_config_file) as json_file:
            self.topology = json.load(json_file)

    def add_participant_config(self, participant_config):
        with open(participant_config) as json_file:
            self.participants.append(json.load(json_file))

    def set_participants_config(self, participants_config):
        self.participants = []
        self.participants_path = participants_config
        for participant in participants_config:
            self.add_participant_config(participant)

    def add_participants_config(self, participants_config):
        self.participants_path = participants_config
        for participant in participants_config:
            self.add_participant_config(participant)

    def add_neighbor_from_config(self, addr):
        if self.participant != {}:
            if self.participant["network_args"]["neighbors"] == "":
                self.participant["network_args"]["neighbors"] = addr
                self.participant["mobility_args"]["neighbors_distance"][addr] = None
            else:
                if addr not in self.participant["network_args"]["neighbors"]:
                    self.participant["network_args"]["neighbors"] += " " + addr
                    self.participant["mobility_args"]["neighbors_distance"][addr] = None

    def update_nodes_distance(self, distances: dict):
        self.participant["mobility_args"]["neighbors_distance"] = {node: dist for node, (dist, _) in distances.items()}

    def update_neighbors_from_config(self, current_connections, dest_addr):
        final_neighbors = []
        for n in current_connections:
            if n != dest_addr:
                final_neighbors.append(n)

        final_neighbors_string = " ".join(final_neighbors)
        # Update neighbors
        self.participant["network_args"]["neighbors"] = final_neighbors_string
        # Update neighbors location
        self.participant["mobility_args"]["neighbors_distance"] = {
            n: self.participant["mobility_args"]["neighbors_distance"][n]
            for n in final_neighbors
            if n in self.participant["mobility_args"]["neighbors_distance"]
        }
        logging.info(f"Final neighbors: {final_neighbors_string} (config updated))")

    def remove_neighbor_from_config(self, addr):
        if self.participant != {}:
            if self.participant["network_args"]["neighbors"] != "":
                self.participant["network_args"]["neighbors"] = (
                    self.participant["network_args"]["neighbors"].replace(addr, "").replace("  ", " ").strip()
                )

    def reload_config_file(self):
        config_dir = self.participant["tracking_args"]["config_dir"]
        with open(
            f"{config_dir}/participant_{self.participant['device_args']['idx']}.json",
            "w",
        ) as f:
            f.write(self.to_json())
