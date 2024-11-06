import os

from torchvision import transforms
from torchvision.datasets import MNIST


class MNISTDatasetScikit:
    mnist_train = None
    mnist_val = None

    def __init__(self, partition_id=0, partitions_number=1, iid=True):
        self.partition_id = partition_id
        self.partitions_number = partitions_number
        self.iid = iid

        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        os.makedirs(data_dir, exist_ok=True)

        if MNISTDatasetScikit.mnist_train is None:
            MNISTDatasetScikit.mnist_train = MNIST(
                data_dir,
                train=True,
                download=True,
                transform=transforms.ToTensor(),
            )
            if not iid:
                sorted_indexes = MNISTDatasetScikit.mnist_train.targets.sort()[1]
                MNISTDatasetScikit.mnist_train.targets = MNISTDatasetScikit.mnist_train.targets[sorted_indexes]
                MNISTDatasetScikit.mnist_train.data = MNISTDatasetScikit.mnist_train.data[sorted_indexes]

        if MNISTDatasetScikit.mnist_val is None:
            MNISTDatasetScikit.mnist_val = MNIST(
                data_dir,
                train=False,
                download=True,
                transform=transforms.ToTensor(),
            )
            if not iid:
                sorted_indexes = MNISTDatasetScikit.mnist_val.targets.sort()[1]
                MNISTDatasetScikit.mnist_val.targets = MNISTDatasetScikit.mnist_val.targets[sorted_indexes]
                MNISTDatasetScikit.mnist_val.data = MNISTDatasetScikit.mnist_val.data[sorted_indexes]

        self.train_set = MNISTDatasetScikit.mnist_train
        self.test_set = MNISTDatasetScikit.mnist_val

    def train_dataloader(self):
        X_train = self.train_set.data.numpy().reshape(-1, 28 * 28)
        y_train = self.train_set.targets.numpy()
        return X_train, y_train

    def test_dataloader(self):
        X_test = self.test_set.data.numpy().reshape(-1, 28 * 28)
        y_test = self.test_set.targets.numpy()
        return X_test, y_test
