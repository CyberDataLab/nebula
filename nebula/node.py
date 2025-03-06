import os
import random
import sys
import time
import warnings

import torch

torch.multiprocessing.set_start_method("spawn", force=True)

# Ignore CryptographyDeprecationWarning (datatime issues with cryptography library)
from cryptography.utils import CryptographyDeprecationWarning

warnings.filterwarnings("ignore", category=CryptographyDeprecationWarning)

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import logging

from nebula.config.config import Config
from nebula.core.datasets.cifar10.cifar10 import CIFAR10PartitionHandler
from nebula.core.datasets.cifar100.cifar100 import CIFAR100PartitionHandler
from nebula.core.datasets.datamodule import DataModule
from nebula.core.datasets.emnist.emnist import EMNISTPartitionHandler
from nebula.core.datasets.fashionmnist.fashionmnist import FashionMNISTPartitionHandler
from nebula.core.datasets.mnist.mnist import MNISTPartitionHandler
from nebula.core.datasets.nebuladataset import NebulaPartition
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
from nebula.core.models.mnist.cnn import MNISTModelCNN
from nebula.core.models.mnist.mlp import MNISTModelMLP
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

    # Adjust the total number of nodes and the index of the current node for CFL, as it doesn't require a specific partition for the server (not used for training)
    if config.participant["scenario_args"]["federation"] == "CFL":
        n_nodes -= 1
        if idx > 0:
            idx -= 1

    dataset = None
    dataset_name = config.participant["data_args"]["dataset"]
    handler = None
    batch_size = None
    num_workers = config.participant["data_args"]["num_workers"]
    model = None

    if dataset_name == "MNIST":
        batch_size = 32
        handler = MNISTPartitionHandler
        if model_name == "MLP":
            model = MNISTModelMLP()
        elif model_name == "CNN":
            model = MNISTModelCNN()
        else:
            raise ValueError(f"Model {model} not supported for dataset {dataset_name}")
    elif dataset_name == "FashionMNIST":
        batch_size = 32
        handler = FashionMNISTPartitionHandler
        if model_name == "MLP":
            model = FashionMNISTModelMLP()
        elif model_name == "CNN":
            model = FashionMNISTModelCNN()
        else:
            raise ValueError(f"Model {model} not supported for dataset {dataset_name}")
    elif dataset_name == "EMNIST":
        batch_size = 32
        handler = EMNISTPartitionHandler
        if model_name == "MLP":
            model = EMNISTModelMLP()
        elif model_name == "CNN":
            model = EMNISTModelCNN()
        else:
            raise ValueError(f"Model {model} not supported for dataset {dataset_name}")
    elif dataset_name == "CIFAR10":
        batch_size = 32
        handler = CIFAR10PartitionHandler
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
            raise ValueError(f"Model {model} not supported for dataset {dataset_name}")
    elif dataset_name == "CIFAR100":
        batch_size = 128
        handler = CIFAR100PartitionHandler
        if model_name == "CNN":
            model = CIFAR100ModelCNN()
        else:
            raise ValueError(f"Model {model} not supported for dataset {dataset_name}")
    else:
        raise ValueError(f"Dataset {dataset_name} not supported")

    dataset = NebulaPartition(handler=handler, mode="memory", config=config)
    dataset.load_partition()
    dataset.log_partition()

    datamodule = DataModule(
        train_set=dataset.train_set,
        train_set_indices=dataset.train_indices,
        test_set=dataset.test_set,
        test_set_indices=dataset.test_indices,
        local_test_set_indices=dataset.local_test_indices,
        num_workers=num_workers,
        batch_size=batch_size,
    )

    trainer = None
    trainer_str = config.participant["training_args"]["trainer"]
    if trainer_str == "lightning":
        trainer = Lightning
    elif trainer_str == "scikit":
        raise NotImplementedError
    elif trainer_str == "siamese" and dataset_name == "CIFAR10":
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
        datamodule=datamodule,
        config=config,
        trainer=trainer,
        security=False,
    )
    await node.start_communications()
    await node.deploy_federation()

    # If it is an additional node, it should wait until additional_node_round to connect to the network
    # In order to do that, it should request the current round to the controller
    if additional_node_status:
        logging.info(f"Waiting for round {additional_node_round} to start")
        logging.info("Waiting time to start finding federation")

        await asyncio.sleep(6000)  # DEBUG purposes

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
