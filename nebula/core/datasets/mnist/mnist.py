import os

from PIL import Image
from torchvision import transforms
from torchvision.datasets import MNIST

from nebula.core.datasets.nebuladataset import NebulaDataset, NebulaPartitionHandler


class MNISTPartitionHandler(NebulaPartitionHandler):
    def __init__(self, file_path, prefix, config, empty=False):
        super().__init__(file_path, prefix, config, empty)

        # Custom transform for MNIST
        self.transform = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize((0.5,), (0.5,), inplace=True),
        ])

    def __getitem__(self, idx):
        data, target = super().__getitem__(idx)

        # MNIST from torchvision returns a tuple (image, target)
        if isinstance(data, tuple):
            img, _ = data
        else:
            img = data

        # Only convert if not already a PIL image
        if not isinstance(img, Image.Image):
            img = Image.fromarray(img, mode="L")

        if self.transform is not None:
            img = self.transform(img)

        if self.target_transform is not None:
            target = self.target_transform(target)

        return img, target


class MNISTDataset(NebulaDataset):
    def __init__(
        self,
        num_classes=10,
        partitions_number=1,
        batch_size=32,
        num_workers=4,
        iid=True,
        partition="dirichlet",
        partition_parameter=0.5,
        seed=42,
        config_dir=None,
    ):
        super().__init__(
            num_classes=num_classes,
            partitions_number=partitions_number,
            batch_size=batch_size,
            num_workers=num_workers,
            iid=iid,
            partition=partition,
            partition_parameter=partition_parameter,
            seed=seed,
            config_dir=config_dir,
        )

    def initialize_dataset(self):
        if self.train_set is None:
            self.train_set = self.load_mnist_dataset(train=True)
        if self.test_set is None:
            self.test_set = self.load_mnist_dataset(train=False)

        self.data_partitioning(plot=True)

    def load_mnist_dataset(self, train=True):
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        os.makedirs(data_dir, exist_ok=True)
        return MNIST(
            data_dir,
            train=train,
            download=True,
        )

    def generate_non_iid_map(self, dataset, partition="dirichlet", partition_parameter=0.5, num_clients=None):
        if partition == "dirichlet":
            partitions_map = self.dirichlet_partition(dataset, alpha=partition_parameter, n_clients=num_clients)
        elif partition == "percent":
            partitions_map = self.percentage_partition(dataset, percentage=partition_parameter, n_clients=num_clients)
        else:
            raise ValueError(f"Partition {partition} is not supported for Non-IID map")

        return partitions_map

    def generate_iid_map(self, dataset, partition="balancediid", partition_parameter=2, num_clients=None):
        if partition == "balancediid":
            partitions_map = self.balanced_iid_partition(dataset, n_clients=num_clients)
        elif partition == "unbalancediid":
            partitions_map = self.unbalanced_iid_partition(
                dataset, imbalance_factor=partition_parameter, n_clients=num_clients
            )
        else:
            raise ValueError(f"Partition {partition} is not supported for IID map")

        return partitions_map
