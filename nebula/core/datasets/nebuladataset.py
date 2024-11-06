import time
from abc import ABC, abstractmethod
from collections import defaultdict

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns
from sklearn.manifold import TSNE
from torch.utils.data import Dataset

matplotlib.use("Agg")
plt.switch_backend("Agg")

import logging

from nebula.config.config import TRAINING_LOGGER
from nebula.core.utils.deterministic import enable_deterministic

logging_training = logging.getLogger(TRAINING_LOGGER)


class NebulaDataset(Dataset, ABC):
    """
    Abstract class for a partitioned dataset.

    Classes inheriting from this class need to implement specific methods
    for loading and partitioning the dataset.
    """

    def __init__(
        self,
        num_classes=10,
        partition_id=0,
        partitions_number=1,
        batch_size=32,
        num_workers=4,
        iid=True,
        partition="dirichlet",
        partition_parameter=0.5,
        seed=42,
        config=None,
    ):
        super().__init__()

        if partition_id < 0 or partition_id >= partitions_number:
            raise ValueError(f"partition_id {partition_id} is out of range for partitions_number {partitions_number}")

        self.num_classes = num_classes
        self.partition_id = partition_id
        self.partitions_number = partitions_number
        self.batch_size = batch_size
        self.num_workers = num_workers
        self.iid = iid
        self.partition = partition
        self.partition_parameter = partition_parameter
        self.seed = seed
        self.config = config

        self.train_set = None
        self.train_indices_map = None
        self.test_set = None
        self.test_indices_map = None

        # Classes of the participants to be sure that the same classes are used in training and testing
        self.class_distribution = None

        enable_deterministic(config)

        if self.partition_id == 0:
            self.initialize_dataset()
        else:
            max_tries = 10
            for i in range(max_tries):
                try:
                    self.initialize_dataset()
                    break
                except Exception as e:
                    logging_training.info(f"Error loading dataset: {e}. Retrying {i + 1}/{max_tries} in 5 seconds...")
                    time.sleep(5)

    @abstractmethod
    def initialize_dataset(self):
        """
        Initialize the dataset. This should load or create the dataset.
        """
        pass

    @abstractmethod
    def generate_non_iid_map(self, dataset, partition="dirichlet", plot=False):
        """
        Create a non-iid map of the dataset.
        """
        pass

    @abstractmethod
    def generate_iid_map(self, dataset, plot=False):
        """
        Create an iid map of the dataset.
        """
        pass

    def get_train_labels(self):
        """
        Get the labels of the training set based on the indices map.
        """
        if self.train_indices_map is None:
            return None
        return [self.train_set.targets[idx] for idx in self.train_indices_map]

    def get_test_labels(self):
        """
        Get the labels of the test set based on the indices map.
        """
        if self.test_indices_map is None:
            return None
        return [self.test_set.targets[idx] for idx in self.test_indices_map]

    def get_local_test_labels(self):
        """
        Get the labels of the local test set based on the indices map.
        """
        if self.local_test_indices_map is None:
            return None
        return [self.test_set.targets[idx] for idx in self.local_test_indices_map]

    def plot_data_distribution(self, dataset, partitions_map):
        """
        Plot the data distribution of the dataset.

        Plot the data distribution of the dataset according to the partitions map provided.

        Args:
            dataset: The dataset to plot (torch.utils.data.Dataset).
            partitions_map: The map of the dataset partitions.
        """
        # Plot the data distribution of the dataset, one graph per partition
        sns.set()
        sns.set_style("whitegrid", {"axes.grid": False})
        sns.set_context("paper", font_scale=1.5)
        sns.set_palette("Set2")

        for i in range(self.partitions_number):
            indices = partitions_map[i]
            class_counts = [0] * self.num_classes
            for idx in indices:
                label = dataset.targets[idx]
                class_counts[label] += 1
            logging_training.info(f"Participant {i + 1} class distribution: {class_counts}")
            plt.figure()
            plt.bar(range(self.num_classes), class_counts)
            plt.xlabel("Class")
            plt.ylabel("Number of samples")
            plt.xticks(range(self.num_classes))
            if self.iid:
                plt.title(f"Participant {i + 1} class distribution (IID)")
            else:
                plt.title(
                    f"Participant {i + 1} class distribution (Non-IID - {self.partition}) - {self.partition_parameter}"
                )
            plt.tight_layout()
            path_to_save = f"{self.config.participant['tracking_args']['log_dir']}/{self.config.participant['scenario_args']['name']}/participant_{i}_class_distribution_{'iid' if self.iid else 'non_iid'}{'_' + self.partition if not self.iid else ''}.png"
            plt.savefig(path_to_save, dpi=300, bbox_inches="tight")
            plt.close()

        plt.figure()
        max_point_size = 500
        min_point_size = 0

        for i in range(self.partitions_number):
            class_counts = [0] * self.num_classes
            indices = partitions_map[i]
            for idx in indices:
                label = dataset.targets[idx]
                class_counts[label] += 1

            # Normalize the point sizes for this partition
            max_samples_partition = max(class_counts)
            sizes = [
                (size / max_samples_partition) * (max_point_size - min_point_size) + min_point_size
                for size in class_counts
            ]
            plt.scatter([i] * self.num_classes, range(self.num_classes), s=sizes, alpha=0.5)

        plt.xlabel("Participant")
        plt.ylabel("Class")
        plt.xticks(range(self.partitions_number))
        plt.yticks(range(self.num_classes))
        if self.iid:
            plt.title(f"Participant {i + 1} class distribution (IID)")
        else:
            plt.title(
                f"Participant {i + 1} class distribution (Non-IID - {self.partition}) - {self.partition_parameter}"
            )
        plt.tight_layout()

        # Saves the distribution display with circles of different size
        path_to_save = f"{self.config.participant['tracking_args']['log_dir']}/{self.config.participant['scenario_args']['name']}/class_distribution_{'iid' if self.iid else 'non_iid'}{'_' + self.partition if not self.iid else ''}.png"
        plt.savefig(path_to_save, dpi=300, bbox_inches="tight")
        plt.close()

        if hasattr(self, "tsne") and self.tsne:
            self.visualize_tsne(dataset)

    def visualize_tsne(self, dataset):
        X = []  # List for storing the characteristics of the samples
        y = []  # Ready to store the labels of the samples
        for idx in range(len(dataset)):  # Assuming that 'dataset' is a list or array of your samples
            sample, label = dataset[idx]
            X.append(sample.flatten())
            y.append(label)

        X = np.array(X)
        y = np.array(y)

        tsne = TSNE(n_components=2, verbose=1, perplexity=40, n_iter=300)
        tsne_results = tsne.fit_transform(X)

        plt.figure(figsize=(16, 10))
        sns.scatterplot(
            x=tsne_results[:, 0],
            y=tsne_results[:, 1],
            hue=y,
            palette=sns.color_palette("hsv", self.num_classes),
            legend="full",
            alpha=0.7,
        )

        plt.title("t-SNE visualization of the dataset")
        plt.xlabel("t-SNE axis 1")
        plt.ylabel("t-SNE axis 2")
        plt.legend(title="Class")
        plt.tight_layout()

        path_to_save_tsne = f"{self.config.participant['tracking_args']['log_dir']}/{self.config.participant['scenario_args']['name']}/tsne_visualization.png"
        plt.savefig(path_to_save_tsne, dpi=300, bbox_inches="tight")
        plt.close()

    def dirichlet_partition(self, dataset, alpha=0.5, min_samples_per_class=10):
        y_data = self._get_targets(dataset)
        unique_labels = np.unique(y_data)
        logging_training.info(f"Labels unique: {unique_labels}")
        num_samples = len(y_data)

        indices_per_partition = [[] for _ in range(self.partitions_number)]
        label_distribution = self.class_distribution if self.class_distribution is not None else None

        for label in unique_labels:
            label_indices = np.where(y_data == label)[0]
            np.random.shuffle(label_indices)

            if label_distribution is None:
                proportions = np.random.dirichlet([alpha] * self.partitions_number)
            else:
                proportions = label_distribution[label]

            proportions = self._adjust_proportions(proportions, indices_per_partition, num_samples)
            split_points = (np.cumsum(proportions) * len(label_indices)).astype(int)[:-1]

            for partition_idx, indices in enumerate(np.split(label_indices, split_points)):
                if len(indices) < min_samples_per_class:
                    indices_per_partition[partition_idx].extend([])
                else:
                    indices_per_partition[partition_idx].extend(indices)

        if label_distribution is None:
            self.class_distribution = self._calculate_class_distribution(indices_per_partition, y_data)

        return {i: indices for i, indices in enumerate(indices_per_partition)}

    def _adjust_proportions(self, proportions, indices_per_partition, num_samples):
        adjusted = np.array([
            p * (len(indices) < num_samples / self.partitions_number)
            for p, indices in zip(proportions, indices_per_partition, strict=False)
        ])
        return adjusted / adjusted.sum()

    def _calculate_class_distribution(self, indices_per_partition, y_data):
        distribution = defaultdict(lambda: np.zeros(self.partitions_number))
        for partition_idx, indices in enumerate(indices_per_partition):
            labels, counts = np.unique(y_data[indices], return_counts=True)
            for label, count in zip(labels, counts, strict=False):
                distribution[label][partition_idx] = count
        return {k: v / v.sum() for k, v in distribution.items()}

    @staticmethod
    def _get_targets(dataset) -> np.ndarray:
        if isinstance(dataset.targets, np.ndarray):
            return dataset.targets
        elif hasattr(dataset.targets, "numpy"):
            return dataset.targets.numpy()
        else:
            return np.asarray(dataset.targets)

    def homo_partition(self, dataset):
        """
        Homogeneously partition the dataset into multiple subsets.

        This function divides a dataset into a specified number of subsets, where each subset
        is intended to have a roughly equal number of samples. This method aims to ensure a
        homogeneous distribution of data across all subsets. It's particularly useful in
        scenarios where a uniform distribution of data is desired among all federated learning
        clients.

        Args:
            dataset (torch.utils.data.Dataset): The dataset to partition. It should have
                                                'data' and 'targets' attributes.

        Returns:
            dict: A dictionary where keys are subset indices (ranging from 0 to partitions_number-1)
                and values are lists of indices corresponding to the samples in each subset.

        The function randomly shuffles the entire dataset and then splits it into the number
        of subsets specified by `partitions_number`. It ensures that each subset has a similar number
        of samples. The function also prints the class distribution in each subset for reference.

        Example usage:
            federated_data = homo_partition(my_dataset)
            # This creates federated data subsets with homogeneous distribution.
        """
        n_nets = self.partitions_number

        n_train = len(dataset.targets)
        np.random.seed(self.seed)
        idxs = np.random.permutation(n_train)
        batch_idxs = np.array_split(idxs, n_nets)
        net_dataidx_map = {i: batch_idxs[i] for i in range(n_nets)}

        # partitioned_datasets = []
        for i in range(self.partitions_number):
            # subset = torch.utils.data.Subset(dataset, net_dataidx_map[i])
            # partitioned_datasets.append(subset)

            # Print class distribution in the current partition
            class_counts = [0] * self.num_classes
            for idx in net_dataidx_map[i]:
                label = dataset.targets[idx]
                class_counts[label] += 1
            logging_training.info(f"Partition {i + 1} class distribution: {class_counts}")

        return net_dataidx_map

    def balanced_iid_partition(self, dataset):
        """
        Partition the dataset into balanced and IID (Independent and Identically Distributed)
        subsets for each client.

        This function divides a dataset into a specified number of subsets (federated clients),
        where each subset has an equal class distribution. This makes the partition suitable for
        simulating IID data scenarios in federated learning.

        Args:
            dataset (list): The dataset to partition. It should be a list of tuples where each
                            tuple represents a data sample and its corresponding label.

        Returns:
            dict: A dictionary where keys are client IDs (ranging from 0 to partitions_number-1) and
                    values are lists of indices corresponding to the samples assigned to each client.

        The function ensures that each class is represented equally in each subset. The
        partitioning process involves iterating over each class, shuffling the indices of that class,
        and then splitting them equally among the clients. The function does not print the class
        distribution in each subset.

        Example usage:
            federated_data = balanced_iid_partition(my_dataset)
            # This creates federated data subsets with equal class distributions.
        """
        num_clients = self.partitions_number
        clients_data = {i: [] for i in range(num_clients)}

        # Get the labels from the dataset
        if isinstance(dataset.targets, np.ndarray):
            labels = dataset.targets
        elif hasattr(dataset.targets, "numpy"):  # Check if it's a tensor with .numpy() method
            labels = dataset.targets.numpy()
        else:  # If it's a list
            labels = np.asarray(dataset.targets)

        label_counts = np.bincount(labels)
        min_label = label_counts.argmin()
        min_count = label_counts[min_label]

        for label in range(self.num_classes):
            # Get the indices of the same label samples
            label_indices = np.where(labels == label)[0]
            np.random.seed(self.seed)
            np.random.shuffle(label_indices)

            # Split the data based on their labels
            samples_per_client = min_count // num_clients

            for i in range(num_clients):
                start_idx = i * samples_per_client
                end_idx = (i + 1) * samples_per_client
                clients_data[i].extend(label_indices[start_idx:end_idx])

        return clients_data

    def unbalanced_iid_partition(self, dataset, imbalance_factor=2):
        """
        Partition the dataset into multiple IID (Independent and Identically Distributed)
        subsets with different size.

        This function divides a dataset into a specified number of IID subsets (federated
        clients), where each subset has a different number of samples. The number of samples
        in each subset is determined by an imbalance factor, making the partition suitable
        for simulating imbalanced data scenarios in federated learning.

        Args:
            dataset (list): The dataset to partition. It should be a list of tuples where
                            each tuple represents a data sample and its corresponding label.
            imbalance_factor (float): The factor to determine the degree of imbalance
                                    among the subsets. A lower imbalance factor leads to more
                                    imbalanced partitions.

        Returns:
            dict: A dictionary where keys are client IDs (ranging from 0 to partitions_number-1) and
                    values are lists of indices corresponding to the samples assigned to each client.

        The function ensures that each class is represented in each subset but with varying
        proportions. The partitioning process involves iterating over each class, shuffling
        the indices of that class, and then splitting them according to the calculated subset
        sizes. The function does not print the class distribution in each subset.

        Example usage:
            federated_data = unbalanced_iid_partition(my_dataset, imbalance_factor=2)
            # This creates federated data subsets with varying number of samples based on
            # an imbalance factor of 2.
        """
        num_clients = self.partitions_number
        clients_data = {i: [] for i in range(num_clients)}

        # Get the labels from the dataset
        labels = np.array([dataset.targets[idx] for idx in range(len(dataset))])
        label_counts = np.bincount(labels)

        min_label = label_counts.argmin()
        min_count = label_counts[min_label]

        # Set the initial_subset_size
        initial_subset_size = min_count // num_clients

        # Calculate the number of samples for each subset based on the imbalance factor
        subset_sizes = [initial_subset_size]
        for i in range(1, num_clients):
            subset_sizes.append(int(subset_sizes[i - 1] * ((imbalance_factor - 1) / imbalance_factor)))

        for label in range(self.num_classes):
            # Get the indices of the same label samples
            label_indices = np.where(labels == label)[0]
            np.random.seed(self.seed)
            np.random.shuffle(label_indices)

            # Split the data based on their labels
            start = 0
            for i in range(num_clients):
                end = start + subset_sizes[i]
                clients_data[i].extend(label_indices[start:end])
                start = end

        return clients_data

    def percentage_partition(self, dataset, percentage=20):
        """
        Partition a dataset into multiple subsets with a specified level of non-IID-ness.

        This function divides a dataset into a specified number of subsets (federated
        clients), where each subset has a different class distribution. The class
        distribution in each subset is determined by a specified percentage, making the
        partition suitable for simulating non-IID (non-Independently and Identically
        Distributed) data scenarios in federated learning.

        Args:
            dataset (torch.utils.data.Dataset): The dataset to partition. It should have
                                                'data' and 'targets' attributes.
            percentage (int): A value between 0 and 100 that specifies the desired
                                level of non-IID-ness for the labels of the federated data.
                                This percentage controls the imbalance in the class distribution
                                across different subsets.

        Returns:
            dict: A dictionary where keys are subset indices (ranging from 0 to partitions_number-1)
                and values are lists of indices corresponding to the samples in each subset.

        The function ensures that the number of classes in each subset varies based on the selected
        percentage. The partitioning process involves iterating over each class, shuffling the
        indices of that class, and then splitting them according to the calculated subset sizes.
        The function also prints the class distribution in each subset for reference.

        Example usage:
            federated_data = percentage_partition(my_dataset, percentage=20)
            # This creates federated data subsets with varying class distributions based on
            # a percentage of 20.
        """
        if isinstance(dataset.targets, np.ndarray):
            y_train = dataset.targets
        elif hasattr(dataset.targets, "numpy"):  # Check if it's a tensor with .numpy() method
            y_train = dataset.targets.numpy()
        else:  # If it's a list
            y_train = np.asarray(dataset.targets)

        num_classes = self.num_classes
        num_subsets = self.partitions_number
        class_indices = {i: np.where(y_train == i)[0] for i in range(num_classes)}

        # Get the labels from the dataset
        labels = np.array([dataset.targets[idx] for idx in range(len(dataset))])
        label_counts = np.bincount(labels)

        min_label = label_counts.argmin()
        min_count = label_counts[min_label]

        classes_per_subset = int(num_classes * percentage / 100)
        if classes_per_subset < 1:
            raise ValueError("The percentage is too low to assign at least one class to each subset.")

        subset_indices = [[] for _ in range(num_subsets)]
        class_list = list(range(num_classes))
        np.random.seed(self.seed)
        np.random.shuffle(class_list)

        for i in range(num_subsets):
            for j in range(classes_per_subset):
                # Use modulo operation to cycle through the class_list
                class_idx = class_list[(i * classes_per_subset + j) % num_classes]
                indices = class_indices[class_idx]
                np.random.seed(self.seed)
                np.random.shuffle(indices)
                # Select approximately 50% of the indices
                subset_indices[i].extend(indices[: min_count // 2])

            class_counts = np.bincount(np.array([dataset.targets[idx] for idx in subset_indices[i]]))
            logging_training.info(f"Partition {i + 1} class distribution: {class_counts.tolist()}")

        partitioned_datasets = {i: subset_indices[i] for i in range(num_subsets)}

        return partitioned_datasets

    def plot_all_data_distribution(self, dataset, partitions_map):
        """

        Plot all of the data distribution of the dataset according to the partitions map provided.

        Args:
            dataset: The dataset to plot (torch.utils.data.Dataset).
            partitions_map: The map of the dataset partitions.
        """
        sns.set()
        sns.set_style("whitegrid", {"axes.grid": False})
        sns.set_context("paper", font_scale=1.5)
        sns.set_palette("Set2")

        num_clients = len(partitions_map)
        num_classes = self.num_classes

        plt.figure(figsize=(12, 8))

        label_distribution = [[] for _ in range(num_classes)]
        for c_id, idc in partitions_map.items():
            for idx in idc:
                label_distribution[dataset.targets[idx]].append(c_id)

        plt.hist(
            label_distribution,
            stacked=True,
            bins=np.arange(-0.5, num_clients + 1.5, 1),
            label=dataset.classes,
            rwidth=0.5,
        )
        plt.xticks(
            np.arange(num_clients),
            ["Participant %d" % (c_id + 1) for c_id in range(num_clients)],
        )
        plt.title("Distribution of splited datasets")
        plt.xlabel("Participant")
        plt.ylabel("Number of samples")
        plt.xticks(range(num_clients), [f" {i}" for i in range(num_clients)])
        plt.legend(loc="upper right")
        plt.tight_layout()

        path_to_save = f"{self.config.participant['tracking_args']['log_dir']}/{self.config.participant['scenario_args']['name']}/all_data_distribution_{'iid' if self.iid else 'non_iid'}{'_' + self.partition if not self.iid else ''}.png"
        plt.savefig(path_to_save, dpi=300, bbox_inches="tight")
        plt.close()
