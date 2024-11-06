import os
import random
import sys
import time
import warnings

import numpy as np
import torch

torch.multiprocessing.set_start_method("spawn", force=True)

# Ignore CryptographyDeprecationWarning (datatime issues with cryptography library)
from cryptography.utils import CryptographyDeprecationWarning

warnings.filterwarnings("ignore", category=CryptographyDeprecationWarning)

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import logging

from nebula.config.config import Config
from nebula.core.datasets.cifar10.cifar10 import CIFAR10Dataset
from nebula.core.datasets.cifar100.cifar100 import CIFAR100Dataset
from nebula.core.datasets.datamodule import DataModule
from nebula.core.datasets.emnist.emnist import EMNISTDataset
from nebula.core.datasets.fashionmnist.fashionmnist import FashionMNISTDataset
from nebula.core.datasets.kitsun.kitsun import KITSUNDataset
from nebula.core.datasets.militarysar.militarysar import MilitarySARDataset
from nebula.core.datasets.mnist.mnist import MNISTDataset
from nebula.core.datasets.syscall.syscall import SYSCALLDataset
from nebula.core.engine import AggregatorNode, IdleNode, MaliciousNode, ServerNode, TrainerNode
from nebula.core.models.cifar10.cnn import CIFAR10ModelCNN
from nebula.core.models.cifar10.cnnV2 import CIFAR10ModelCNN_V2
from nebula.core.models.cifar10.cnnV3 import CIFAR10ModelCNN_V3
from nebula.core.models.cifar10.dualagg import DualAggModel
from nebula.core.models.cifar10.fastermobilenet import FasterMobileNet
from nebula.core.models.cifar10.resnet import CIFAR10ModelResNet
from nebula.core.models.cifar10.simplemobilenet import SimpleMobileNetV1
from nebula.core.models.cifar100.cnn import CIFAR100ModelCNN
from nebula.core.models.emnist.cnn import EMNISTModelCNN
from nebula.core.models.emnist.mlp import EMNISTModelMLP
from nebula.core.models.fashionmnist.cnn import FashionMNISTModelCNN
from nebula.core.models.fashionmnist.mlp import FashionMNISTModelMLP
from nebula.core.models.kitsun.mlp import KitsunModelMLP
from nebula.core.models.militarysar.cnn import MilitarySARModelCNN
from nebula.core.models.mnist.cnn import MNISTModelCNN
from nebula.core.models.mnist.mlp import MNISTModelMLP
from nebula.core.models.syscall.autoencoder import SyscallModelAutoencoder
from nebula.core.models.syscall.mlp import SyscallModelMLP
from nebula.core.models.syscall.svm import SyscallModelSGDOneClassSVM
from nebula.core.role import Role
from nebula.core.training.lightning import Lightning
from nebula.core.training.siamese import Siamese

# os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
# os.environ["TORCH_LOGS"] = "+dynamo"
# os.environ["TORCHDYNAMO_VERBOSE"] = "1"


async def main(config):
    n_nodes = config.participant["scenario_args"]["n_nodes"]
    model_name = config.participant["model_args"]["model"]
    idx = config.participant["device_args"]["idx"]

    additional_node_status = config.participant["mobility_args"]["additional_node"]["status"]
    additional_node_round = config.participant["mobility_args"]["additional_node"]["round_start"]

    attacks = config.participant["adversarial_args"]["attacks"]
    poisoned_percent = config.participant["adversarial_args"]["poisoned_sample_percent"]
    poisoned_ratio = config.participant["adversarial_args"]["poisoned_ratio"]
    targeted = str(config.participant["adversarial_args"]["targeted"])
    target_label = config.participant["adversarial_args"]["target_label"]
    target_changed_label = config.participant["adversarial_args"]["target_changed_label"]
    noise_type = config.participant["adversarial_args"]["noise_type"]
    iid = config.participant["data_args"]["iid"]
    partition_selection = config.participant["data_args"]["partition_selection"]
    partition_parameter = np.array(config.participant["data_args"]["partition_parameter"], dtype=np.float64)
    label_flipping = False
    data_poisoning = False
    model_poisoning = False
    if attacks == "Label Flipping":
        label_flipping = True
        poisoned_ratio = 0
        if targeted == "true" or targeted == "True":
            targeted = True
        else:
            targeted = False
    elif attacks == "Sample Poisoning":
        data_poisoning = True
        if targeted == "true" or targeted == "True":
            targeted = True
        else:
            targeted = False
    elif attacks == "Model Poisoning":
        model_poisoning = True
    else:
        label_flipping = False
        data_poisoning = False
        targeted = False
        poisoned_percent = 0
        poisoned_ratio = 0

    # Adjust the total number of nodes and the index of the current node for CFL, as it doesn't require a specific partition for the server (not used for training)
    if config.participant["scenario_args"]["federation"] == "CFL":
        n_nodes -= 1
        if idx > 0:
            idx -= 1

    dataset = None
    dataset_str = config.participant["data_args"]["dataset"]
    num_workers = config.participant["data_args"]["num_workers"]
    model = None
    if dataset_str == "MNIST":
        dataset = MNISTDataset(
            num_classes=10,
            partition_id=idx,
            partitions_number=n_nodes,
            iid=iid,
            partition=partition_selection,
            partition_parameter=partition_parameter,
            seed=42,
            config=config,
        )
        if model_name == "MLP":
            model = MNISTModelMLP()
        elif model_name == "CNN":
            model = MNISTModelCNN()
        else:
            raise ValueError(f"Model {model} not supported for dataset {dataset_str}")
    elif dataset_str == "FashionMNIST":
        dataset = FashionMNISTDataset(
            num_classes=10,
            partition_id=idx,
            partitions_number=n_nodes,
            iid=iid,
            partition=partition_selection,
            partition_parameter=partition_parameter,
            seed=42,
            config=config,
        )
        if model_name == "MLP":
            model = FashionMNISTModelMLP()
        elif model_name == "CNN":
            model = FashionMNISTModelCNN()
        else:
            raise ValueError(f"Model {model} not supported for dataset {dataset_str}")
    elif dataset_str == "EMNIST":
        dataset = EMNISTDataset(
            num_classes=10,
            partition_id=idx,
            partitions_number=n_nodes,
            iid=iid,
            partition=partition_selection,
            partition_parameter=partition_parameter,
            seed=42,
            config=config,
        )
        if model_name == "MLP":
            model = EMNISTModelMLP()
        elif model_name == "CNN":
            model = EMNISTModelCNN()
        else:
            raise ValueError(f"Model {model} not supported for dataset {dataset_str}")
    elif dataset_str == "SYSCALL":
        dataset = SYSCALLDataset(
            num_classes=10,
            partition_id=idx,
            partitions_number=n_nodes,
            iid=iid,
            partition=partition_selection,
            partition_parameter=partition_parameter,
            seed=42,
            config=config,
        )
        if model_name == "MLP":
            model = SyscallModelMLP()
        elif model_name == "SVM":
            model = SyscallModelSGDOneClassSVM()
        elif model_name == "Autoencoder":
            model = SyscallModelAutoencoder()
        else:
            raise ValueError(f"Model {model} not supported for dataset {dataset_str}")
    elif dataset_str == "CIFAR10":
        dataset = CIFAR10Dataset(
            num_classes=10,
            partition_id=idx,
            partitions_number=n_nodes,
            iid=iid,
            partition=partition_selection,
            partition_parameter=partition_parameter,
            seed=42,
            config=config,
        )
        if model_name == "ResNet9":
            model = CIFAR10ModelResNet(classifier="resnet9")
        elif model_name == "fastermobilenet":
            model = FasterMobileNet()
        elif model_name == "simplemobilenet":
            model = SimpleMobileNetV1()
        elif model_name == "CNN":
            model = CIFAR10ModelCNN()
        elif model_name == "CNNv2":
            model = CIFAR10ModelCNN_V2()
        elif model_name == "CNNv3":
            model = CIFAR10ModelCNN_V3()
        else:
            raise ValueError(f"Model {model} not supported for dataset {dataset_str}")
    elif dataset_str == "CIFAR100":
        dataset = CIFAR100Dataset(
            num_classes=100,
            partition_id=idx,
            partitions_number=n_nodes,
            iid=iid,
            partition=partition_selection,
            partition_parameter=partition_parameter,
            seed=42,
            config=config,
        )
        if model_name == "CNN":
            model = CIFAR100ModelCNN()
        else:
            raise ValueError(f"Model {model} not supported for dataset {dataset_str}")
    elif dataset_str == "KITSUN":
        dataset = KITSUNDataset(
            num_classes=10,
            partition_id=idx,
            partitions_number=n_nodes,
            iid=iid,
            partition=partition_selection,
            partition_parameter=partition_parameter,
            seed=42,
            config=config,
        )
        if model_name == "MLP":
            model = KitsunModelMLP()
        else:
            raise ValueError(f"Model {model} not supported for dataset {dataset_str}")
    elif dataset_str == "MilitarySAR":
        dataset = MilitarySARDataset(
            num_classes=10,
            partition_id=idx,
            partitions_number=n_nodes,
            iid=iid,
            partition=partition_selection,
            partition_parameter=partition_parameter,
            seed=42,
            config=config,
        )
        model = MilitarySARModelCNN()
    else:
        raise ValueError(f"Dataset {dataset_str} not supported")

    dataset = DataModule(
        train_set=dataset.train_set,
        train_set_indices=dataset.train_indices_map,
        test_set=dataset.test_set,
        test_set_indices=dataset.test_indices_map,
        local_test_set_indices=dataset.local_test_indices_map,
        num_workers=num_workers,
        partition_id=idx,
        partitions_number=n_nodes,
        batch_size=dataset.batch_size,
        label_flipping=label_flipping,
        data_poisoning=data_poisoning,
        poisoned_percent=poisoned_percent,
        poisoned_ratio=poisoned_ratio,
        targeted=targeted,
        target_label=target_label,
        target_changed_label=target_changed_label,
        noise_type=noise_type,
    )

    # - Import MNISTDatasetScikit (not torch component)
    # - Import scikit-learn model
    # - Import ScikitDataModule
    # - Import Scikit as trainer
    # - Import aggregation algorithm adapted to scikit-learn models (e.g. FedAvgSVM)

    trainer = None
    trainer_str = config.participant["training_args"]["trainer"]
    if trainer_str == "lightning":
        trainer = Lightning
    elif trainer_str == "scikit":
        raise NotImplementedError
    elif trainer_str == "siamese" and dataset_str == "CIFAR10":
        trainer = Siamese
        model = DualAggModel()
        config.participant["model_args"]["model"] = "DualAggModel"
        config.participant["data_args"]["dataset"] = "CIFAR10"
        config.participant["aggregator_args"]["algorithm"] = "DualHistAgg"
    else:
        raise ValueError(f"Trainer {trainer_str} not supported")

    if config.participant["device_args"]["malicious"]:
        node_cls = MaliciousNode
    else:
        if config.participant["device_args"]["role"] == Role.AGGREGATOR:
            node_cls = AggregatorNode
        elif config.participant["device_args"]["role"] == Role.TRAINER:
            node_cls = TrainerNode
        elif config.participant["device_args"]["role"] == Role.SERVER:
            node_cls = ServerNode
        elif config.participant["device_args"]["role"] == Role.IDLE:
            node_cls = IdleNode
        else:
            raise ValueError(f"Role {config.participant['device_args']['role']} not supported")

    VARIABILITY = 0.5

    def randomize_value(value, variability):
        min_value = max(0, value - variability)
        max_value = value + variability
        return random.uniform(min_value, max_value)

    config_keys = [
        ["reporter_args", "report_frequency"],
        ["discoverer_args", "discovery_frequency"],
        ["health_args", "health_interval"],
        ["health_args", "grace_time_health"],
        ["health_args", "check_alive_interval"],
        ["health_args", "send_alive_interval"],
        ["forwarder_args", "forwarder_interval"],
        ["forwarder_args", "forward_messages_interval"],
    ]

    for keys in config_keys:
        value = config.participant
        for key in keys[:-1]:
            value = value[key]
        value[keys[-1]] = randomize_value(value[keys[-1]], VARIABILITY)

    logging.info(f"Starting node {idx} with model {model_name}, trainer {trainer.__name__}, and as {node_cls.__name__}")

    node = node_cls(
        model=model,
        dataset=dataset,
        config=config,
        trainer=trainer,
        security=False,
        model_poisoning=model_poisoning,
        poisoned_ratio=poisoned_ratio,
        noise_type=noise_type,
    )
    await node.start_communications()
    await node.deploy_federation()

    # If it is an additional node, it should wait until additional_node_round to connect to the network
    # In order to do that, it should request the current round to the controller
    if additional_node_status:
        logging.info(f"Waiting for round {additional_node_round} to start")
        time.sleep(6000)  # DEBUG purposes
        import requests

        url = f"http://{node.config.participant['scenario_args']['controller']}/platform/{node.config.participant['scenario_args']['name']}/round"
        current_round = int(requests.get(url).json()["round"])
        while current_round < additional_node_round:
            logging.info(f"Waiting for round {additional_node_round} to start")
            time.sleep(10)
        logging.info(f"Round {additional_node_round} started, connecting to the network")

    if node.cm is not None:
        await node.cm.network_wait()


if __name__ == "__main__":
    config_path = str(sys.argv[1])
    config = Config(entity="participant", participant_config_file=config_path)
    if sys.platform == "win32" or config.participant["scenario_args"]["deployment"] == "docker":
        import asyncio

        asyncio.run(main(config), debug=False)
    else:
        try:
            import uvloop

            uvloop.run(main(config), debug=False)
        except ImportError:
            logging.warning("uvloop not available, using default loop")
            import asyncio

            asyncio.run(main(config), debug=False)
