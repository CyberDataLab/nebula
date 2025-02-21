import os
from abc import ABC, abstractmethod
from typing import Any

import h5py
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


def wait_for_file(file_path):
    """Wait until the given file exists, polling every 'interval' seconds."""
    while not os.path.exists(file_path):
        logging_training.info(f"Waiting for file: {file_path}")
    return


class NebulaPartitionHandler(Dataset, ABC):
    """
    A class to handle the loading of datasets from HDF5 files.
    """

    def __init__(
        self,
        file_path: str,
        prefix: str = "train",
        mode: str = "memory",
    ):
        self.file_path = file_path
        self.prefix = prefix
        self.mode = mode
        self.transform = None
        self.target_transform = None
        self.file = None
        
        self.data = None
        self.targets = None
        self.data_shape = None
        self.num_classes = None
        self.length = None
        
        if self.mode == "memory":
            self.load_data()
        elif self.mode == "lazy":
            self.load_data_lazy()
        else:
            raise ValueError(f"Mode {self.mode} not supported")
        
    def load_data(self):
        with h5py.File(self.file_path, "r") as f:
            dset = f[f"{self.prefix}_data"]
            self.data = np.array(dset)
            self.targets = np.array(f[f"{self.prefix}_targets"])
            self.data_shape = dset.attrs.get("data_shape", dset.shape[1:])
            self.num_classes = dset.attrs.get("num_classes", 0)
            self.length = len(self.data)
        logging_training.info(
            f"[NebulaPartitionHandler - Memory] [{self.prefix}] Loaded {self.length} samples from {self.file_path} with shape {self.data_shape} and {self.num_classes} classes."
        )
        
    def load_data_lazy(self):
        self.file = h5py.File(self.file_path, "r", swmr=True)
        dset = self.file[f"{self.prefix}_data"]
        self.length = dset.shape[0]
        self.data_shape = dset.attrs.get("data_shape", dset.shape[1:])
        self.num_classes = dset.attrs.get("num_classes", 0)
        logging_training.info(
            f"[NebulaPartitionHandler - Lazy] [{self.prefix}] Lazy loaded {self.length} samples from {self.file_path} with shape {self.data_shape} and {self.num_classes} classes."
        )
        
    def close(self):
        if self.file is not None:
            self.file.close()
            self.file = None
            logging_training.info(f"[NebulaPartitionHandler] Closed file {self.file_path}")
            
    def __del__(self):
        self.close()
        
    def __len__(self):
        return self.length

    def __del__(self):
        if self.file is not None:
            self.file.close()

    def __getitem__(self, idx):
        if self.mode == "memory":
            data = self.data[idx]
            target = self.targets[idx]
        else:
            try:
                data = self.file[f"{self.prefix}_data"][idx]
                target = self.file[f"{self.prefix}_targets"][idx]
            except Exception as e:
                raise RuntimeError(f"[NebulaPartitionHandler] Error reading index {idx} from file {self.file_path}: {e}")

        return data, target


class NebulaPartition:
    """
    A class to handle the partitioning of datasets for federated learning.
    """

    def __init__(self, handler: NebulaPartitionHandler, mode: str, config: dict[str, Any]):
        self.handler = handler
        self.mode = mode
        self.config = config
        
        if self.mode not in ["lazy", "memory"]:
            raise ValueError(f"Mode {self.mode} not supported")

        self.train_set = None
        self.train_indices = None

        self.test_set = None
        self.test_indices = None
        self.local_test_indices = None

        enable_deterministic(seed=self.config.participant["scenario_args"]["random_seed"])

    def get_train_indices(self):
        """
        Get the indices of the training set based on the indices map.
        """
        if self.train_indices is None:
            return None
        return self.train_indices

    def get_test_indices(self):
        """
        Get the indices of the test set based on the indices map.
        """
        if self.test_indices is None:
            return None
        return self.test_indices

    def get_local_test_indices(self):
        """
        Get the indices of the local test set based on the indices map.
        """
        if self.local_test_indices is None:
            return None
        return self.local_test_indices

    def get_train_labels(self):
        """
        Get the labels of the training set based on the indices map.
        """
        if self.train_indices is None:
            return None
        return [self.train_set.targets[idx] for idx in self.train_indices]

    def get_test_labels(self):
        """
        Get the labels of the test set based on the indices map.
        """
        if self.test_indices is None:
            return None
        return [self.test_set.targets[idx] for idx in self.test_indices]

    def get_local_test_labels(self):
        """
        Get the labels of the test set based on the indices map.
        """
        if self.local_test_indices is None:
            return None
        return [self.test_set.targets[idx] for idx in self.local_test_indices]

    def set_local_test_indices(self):
        """
        Set the local test indices for the current node.
        """
        test_labels = self.get_test_labels()
        train_labels = self.get_train_labels()
        return [idx for idx in range(len(self.test_set)) if test_labels[idx] in train_labels]

    def log_partition(self):
        logging_training.info(f"{'=' * 10}")
        logging_training.info(
            f"LOG NEBULA PARTITION DATASET [Participant {self.config.participant['device_args']['idx']}]"
        )
        logging_training.info(f"{'=' * 10}")
        logging_training.info(f"TRAIN - Train labels unique: {set(self.get_train_labels())}")
        logging_training.info(f"TRAIN - Length of train indices map: {len(self.get_train_indices())}")
        logging_training.info(f"{'=' * 10}")
        logging_training.info(f"LOCAL - Test labels unique: {set(self.get_local_test_labels())}")
        logging_training.info(f"LOCAL - Length of test indices map: {len(self.get_local_test_indices())}")
        logging_training.info(f"{'=' * 10}")
        logging_training.info(f"GLOBAL - Test labels unique: {set(self.get_test_labels())}")
        logging_training.info(f"GLOBAL - Length of test indices map: {len(self.get_test_indices())}")
        logging_training.info(f"{'=' * 10}")

    def load_partition(self):
        """
        Load only the partition data corresponding to the current node.
        The node loads its train, test, and local test partition data from HDF5 files.
        """
        try:
            p = self.config.participant["device_args"]["idx"]
            logging_training.info(f"Loading partition data for participant {p}")
            path = self.config.participant["tracking_args"]["config_dir"]

            train_partition_file = os.path.join(path, f"participant_{p}_train.h5")
            wait_for_file(train_partition_file)
            logging_training.info(f"Loading train data from {train_partition_file}")
            self.train_set = self.handler(train_partition_file, "train", mode=self.mode)
            self.train_indices = list(range(len(self.train_set)))

            test_partition_file = os.path.join(path, "global_test.h5")
            wait_for_file(test_partition_file)
            logging_training.info(f"Loading test data from {test_partition_file}")
            self.test_set = self.handler(test_partition_file, "test", mode=self.mode)
            self.test_indices = list(range(len(self.test_set)))
            self.local_test_indices = self.set_local_test_indices()

            logging_training.info(f"Successfully loaded partition data for participant {p}.")
        except Exception as e:
            logging_training.error(f"Error loading partition: {e}")
            raise


class NebulaDataset:
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
        self.num_classes = num_classes
        self.partitions_number = partitions_number
        self.batch_size = batch_size
        self.num_workers = num_workers
        self.iid = iid
        self.partition = partition
        self.partition_parameter = partition_parameter
        self.seed = seed
        self.config_dir = config_dir

        logging.info(
            f"Dataset {self.__class__.__name__} initialized | Partitions: {self.partitions_number} | IID: {self.iid} | Partition: {self.partition} | Partition parameter: {self.partition_parameter}"
        )

        # Dataset
        self.train_set = None
        self.train_indices_map = None
        self.test_set = None
        self.test_indices_map = None
        self.local_test_indices_map = None

        enable_deterministic(self.seed)

    @abstractmethod
    def initialize_dataset(self):
        """
        Initialize the dataset. This should load or create the dataset.
        """
        raise NotImplementedError("Subclasses must implement this method.")
    
    def clear(self):
        """
        Clear the dataset. This should remove or reset the dataset.
        """
        if self.train_set is not None and hasattr(self.train_set, "close"):
            self.train_set.close()
        if self.test_set is not None and hasattr(self.test_set, "close"):
            self.test_set.close()
            
        self.train_set = None
        self.train_indices_map = None
        self.test_set = None
        self.test_indices_map = None
        self.local_test_indices_map = None

    def data_partitioning(self, plot=False):
        """
        Perform the data partitioning.
        """

        logging.info(
            f"Partitioning data for {self.__class__.__name__} | Partitions: {self.partitions_number} | IID: {self.iid} | Partition: {self.partition} | Partition parameter: {self.partition_parameter}"
        )

        self.train_indices_map = (
            self.generate_iid_map(self.train_set)
            if self.iid
            else self.generate_non_iid_map(self.train_set, self.partition, self.partition_parameter)
        )
        self.test_indices_map = self.get_test_indices_map()
        self.local_test_indices_map = self.get_local_test_indices_map()

        if plot:
            self.plot_data_distribution("train", self.train_set, self.train_indices_map)
            self.plot_all_data_distribution("train", self.train_set, self.train_indices_map)
            self.plot_data_distribution("local_test", self.test_set, self.local_test_indices_map)
            self.plot_all_data_distribution("local_test", self.test_set, self.local_test_indices_map)

        self.save_partitions()

    def get_test_indices_map(self):
        """
        Get the indices of the test set for each participant.

        Returns:
            A dictionary mapping participant_id to a list of indices.
        """
        try:
            test_indices_map = {}
            for participant_id in range(self.partitions_number):
                test_indices_map[participant_id] = list(range(len(self.test_set)))
            return test_indices_map
        except Exception as e:
            logging.exception(f"Error in get_test_indices_map: {e}")

    def get_local_test_indices_map(self):
        """
        Get the indices of the local test set for each participant.
        Indices whose labels are the same as the training set are selected.

        Returns:
            A dictionary mapping participant_id to a list of indices.
        """
        try:
            local_test_indices_map = {}
            test_targets = np.array(self.test_set.targets)
            for participant_id in range(self.partitions_number):
                train_labels = np.array([self.train_set.targets[idx] for idx in self.train_indices_map[participant_id]])
                indices = np.where(np.isin(test_targets, train_labels))[0].tolist()
                local_test_indices_map[participant_id] = indices
                logging.info(f"Participant {participant_id} | Local test indices: {indices}")
            return local_test_indices_map
        except Exception as e:
            logging.exception(f"Error in get_local_test_indices_map: {e}")
            raise Exception(f"Error in get_local_test_indices_map: {e}")

    def save_partitions(self):
        """
        Save each partition data (train, test, and local test) to separate pickle files.
        The controller saves one file per partition for each data split.
        """
        try:
            logging.info(f"Saving partitions data for ALL participants ({self.partitions_number}) in {self.config_dir}")
            path = self.config_dir
            if not os.path.exists(path):
                raise FileNotFoundError(f"Path {path} does not exist")
            # Check that the partition maps have the expected number of partitions
            if not (
                len(self.train_indices_map)
                == len(self.test_indices_map)
                == len(self.local_test_indices_map)
                == self.partitions_number
            ):
                raise ValueError("One of the partition maps has an unexpected length.")

            # Save global test data
            file_name = os.path.join(path, "global_test.h5")
            with h5py.File(file_name, "w") as f:
                test_data = np.array(self.test_set.data)
                test_targets = np.array(self.test_set.targets)
                dset = f.create_dataset("test_data", data=test_data, compression="gzip")
                dset.attrs["data_shape"] = test_data.shape[1:]  # Save the shape of the data
                dset.attrs["num_classes"] = self.num_classes  # Save the number of classes
                f.create_dataset("test_targets", data=test_targets, compression="gzip")

            for participant in range(self.partitions_number):
                file_name = os.path.join(path, f"participant_{participant}_train.h5")
                with h5py.File(file_name, "w") as f:
                    logging.info(f"Saving training data for participant {participant} in {file_name}")
                    indices = self.train_indices_map[participant]
                    train_data = np.array([self.train_set.data[i] for i in indices])
                    train_targets = np.array([self.train_set.targets[i] for i in indices])
                    dset = f.create_dataset("train_data", data=train_data, compression="gzip")
                    dset.attrs["data_shape"] = train_data.shape[1:]  # Save the shape of the data
                    dset.attrs["num_classes"] = self.num_classes  # Save the number of classes
                    f.create_dataset("train_targets", data=train_targets, compression="gzip")
                    logging.info(f"Partition saved for participant {participant} with {train_data.shape[0]} samples.")

            logging.info("Successfully saved all partition files.")

        except Exception as e:
            logging.exception(f"Error in save_partitions: {e}")
            
        finally:
            self.clear()
            logging.info("Cleared dataset after saving partitions.")

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

    def plot_data_distribution(self, phase, dataset, partitions_map):
        """
        Plot the data distribution of the dataset.

        Plot the data distribution of the dataset according to the partitions map provided.

        Args:
            phase: The phase of the dataset (train, test, local_test).
            dataset: The dataset to plot (torch.utils.data.Dataset).
            partitions_map: The map of the dataset partitions.
        """
        logging_training.info(f"Plotting data distribution for {phase} dataset")
        # Plot the data distribution of the dataset, one graph per partition
        sns.set()
        sns.set_style("whitegrid", {"axes.grid": False})
        sns.set_context("paper", font_scale=1.5)
        sns.set_palette("Set2")

        # Plot bar charts for each partition
        partition_index = 0
        for partition_index in range(self.partitions_number):
            indices = partitions_map[partition_index]
            class_counts = [0] * self.num_classes
            for idx in indices:
                label = dataset.targets[idx]
                class_counts[label] += 1

            logging_training.info(f"[{phase}] Participant {partition_index} total samples: {len(indices)}")
            logging_training.info(f"[{phase}] Participant {partition_index} data distribution: {class_counts}")

            plt.figure(figsize=(12, 8))
            plt.bar(range(self.num_classes), class_counts)
            for j, count in enumerate(class_counts):
                plt.text(j, count, str(count), ha="center", va="bottom", fontsize=12)
            plt.xlabel("Class")
            plt.ylabel("Number of samples")
            plt.xticks(range(self.num_classes))
            plt.title(
                f"[{phase}] Participant {partition_index} data distribution ({'IID' if self.iid else f'Non-IID - {self.partition}'} - {self.partition_parameter})"
            )
            plt.tight_layout()
            path_to_save = f"{self.config_dir}/participant_{partition_index}_data_distribution_{'iid' if self.iid else 'non_iid'}{'_' + self.partition if not self.iid else ''}_{phase}.pdf"
            logging_training.info(f"Saving data distribution for participant {partition_index} to {path_to_save}")
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

        path_to_save_tsne = f"{self.config_dir}/tsne_visualization.png"
        plt.savefig(path_to_save_tsne, dpi=300, bbox_inches="tight")
        plt.close()

    def dirichlet_partition(
        self,
        dataset: Any,
        alpha: float = 0.5,
        min_samples_size: int = 50,
        balanced: bool = False,
        max_iter: int = 100,
        verbose: bool = True,
    ) -> dict[int, list[int]]:
        """
        Partition the dataset among clients using a Dirichlet distribution.
        This function ensures each client gets at least min_samples_size samples.

        Parameters
        ----------
        dataset : Dataset
            The dataset to partition. Must have a 'targets' attribute.
        alpha : float, default=0.5
            Concentration parameter for the Dirichlet distribution.
        min_samples_size : int, default=50
            Minimum number of samples required in each partition.
        balanced : bool, default=False
            If True, distribute each class evenly among clients.
            Otherwise, allocate according to a Dirichlet distribution.
        max_iter : int, default=100
            Maximum number of iterations to try finding a valid partition.
        verbose : bool, default=True
            If True, print debug information per iteration.

        Returns
        -------
        partitions : dict[int, list[int]]
            Dictionary mapping each client index to a list of sample indices.
        """
        # Extract targets and unique labels.
        y_data = self._get_targets(dataset)
        unique_labels = np.unique(y_data)

        # For each class, get a shuffled list of indices.
        class_indices = {}
        base_rng = np.random.default_rng(self.seed)
        for label in unique_labels:
            idx = np.where(y_data == label)[0]
            base_rng.shuffle(idx)
            class_indices[label] = idx

        # Prepare container for client indices.
        indices_per_partition = [[] for _ in range(self.partitions_number)]

        def allocate_for_label(label_idx: np.ndarray, rng: np.random.Generator) -> np.ndarray:
            num_label_samples = len(label_idx)
            if balanced:
                proportions = np.full(self.partitions_number, 1.0 / self.partitions_number)
            else:
                proportions = rng.dirichlet([alpha] * self.partitions_number)
            sample_counts = (proportions * num_label_samples).astype(int)
            remainder = num_label_samples - sample_counts.sum()
            if remainder > 0:
                extra_indices = rng.choice(self.partitions_number, size=remainder, replace=False)
                for idx in extra_indices:
                    sample_counts[idx] += 1
            return sample_counts

        for iteration in range(1, max_iter + 1):
            rng = np.random.default_rng(self.seed + iteration)
            temp_indices_per_partition = [[] for _ in range(self.partitions_number)]
            for label in unique_labels:
                label_idx = class_indices[label]
                counts = allocate_for_label(label_idx, rng)
                start = 0
                for client_idx, count in enumerate(counts):
                    end = start + count
                    temp_indices_per_partition[client_idx].extend(label_idx[start:end])
                    start = end

            client_sizes = [len(indices) for indices in temp_indices_per_partition]
            if min(client_sizes) >= min_samples_size:
                indices_per_partition = temp_indices_per_partition
                if verbose:
                    print(f"Partition successful at iteration {iteration}. Client sizes: {client_sizes}")
                break
            if verbose:
                print(f"Iteration {iteration}: client sizes {client_sizes}")

        else:
            raise ValueError(
                f"Could not create partitions with at least {min_samples_size} samples per client after {max_iter} iterations."
            )

        initial_partition = {i: indices for i, indices in enumerate(indices_per_partition)}

        final_partition = self.postprocess_partition(initial_partition, y_data)

        return final_partition

    @staticmethod
    def _get_targets(dataset) -> np.ndarray:
        if isinstance(dataset.targets, np.ndarray):
            return dataset.targets
        elif hasattr(dataset.targets, "numpy"):
            return dataset.targets.numpy()
        else:
            return np.asarray(dataset.targets)

    def postprocess_partition(
        self, partition: dict[int, list[int]], y_data: np.ndarray, min_samples_per_class: int = 10
    ) -> dict[int, list[int]]:
        """
        Post-process a partition to remove (and reassign) classes with too few samples per client.

        For each class:
        - For clients with a count > 0 but below min_samples_per_class, remove those samples.
        - Reassign the removed samples to the client that already has the maximum count for that class.

        Parameters
        ----------
        partition : dict[int, list[int]]
            The initial partition mapping client indices to sample indices.
        y_data : np.ndarray
            The array of labels corresponding to the dataset samples.
        min_samples_per_class : int, default=10
            The minimum acceptable number of samples per class for each client.

        Returns
        -------
        new_partition : dict[int, list[int]]
            The updated partition.
        """
        # Copy partition so we can modify it.
        new_partition = {client: list(indices) for client, indices in partition.items()}

        # Iterate over each class.
        for label in np.unique(y_data):
            # For each client, count how many samples of this label exist.
            client_counts = {}
            for client, indices in new_partition.items():
                client_counts[client] = np.sum(np.array(y_data)[indices] == label)

            # Identify clients with fewer than min_samples_per_class but nonzero counts.
            donors = [client for client, count in client_counts.items() if 0 < count < min_samples_per_class]
            # Identify potential recipients: those with at least min_samples_per_class.
            recipients = [client for client, count in client_counts.items() if count >= min_samples_per_class]
            # If no client meets the threshold, choose the one with the highest count.
            if not recipients:
                best_recipient = max(client_counts, key=client_counts.get)
                recipients = [best_recipient]
            # Choose the recipient with the maximum count.
            best_recipient = max(recipients, key=lambda c: client_counts[c])

            # For each donor, remove samples of this label and reassign them.
            for donor in donors:
                donor_indices = new_partition[donor]
                # Identify indices corresponding to this label.
                donor_label_indices = [idx for idx in donor_indices if y_data[idx] == label]
                # Remove these from the donor.
                new_partition[donor] = [idx for idx in donor_indices if y_data[idx] != label]
                # Add these to the best recipient.
                new_partition[best_recipient].extend(donor_label_indices)

        return new_partition

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
            logging.info(f"Partition {i + 1} class distribution: {class_counts}")

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
            logging.info(f"Partition {i + 1} class distribution: {class_counts.tolist()}")

        partitioned_datasets = {i: subset_indices[i] for i in range(num_subsets)}

        return partitioned_datasets

    def plot_all_data_distribution(self, phase, dataset, partitions_map):
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

        # Plot number of samples per class in the dataset
        plt.figure(figsize=(12, 8))

        class_counts = [0] * num_classes
        for target in dataset.targets:
            class_counts[target] += 1

        plt.bar(range(num_classes), class_counts, tick_label=dataset.classes)
        for j, count in enumerate(class_counts):
            plt.text(j, count, str(count), ha="center", va="bottom", fontsize=12)
        plt.title(f"[{phase}] Number of samples per class in the dataset")
        plt.xlabel("Class")
        plt.ylabel("Number of samples")
        plt.tight_layout()

        path_to_save_class_distribution = f"{self.config_dir}/full_data_distribution_{'iid' if self.iid else 'non_iid'}{'_' + self.partition if not self.iid else ''}_{phase}.pdf"
        plt.savefig(path_to_save_class_distribution, dpi=300, bbox_inches="tight")
        plt.close()

        # Plot distribution of samples across participants
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
        plt.title(f"[{phase}] Distribution of splited datasets")
        plt.xlabel("Participant")
        plt.ylabel("Number of samples")
        plt.xticks(range(num_clients), [f" {i}" for i in range(num_clients)])
        plt.legend(loc="upper right")
        plt.tight_layout()

        path_to_save = f"{self.config_dir}/all_data_distribution_HIST_{'iid' if self.iid else 'non_iid'}{'_' + self.partition if not self.iid else ''}_{phase}.pdf"
        plt.savefig(path_to_save, dpi=300, bbox_inches="tight")
        plt.close()

        plt.figure(figsize=(12, 8))
        max_point_size = 1200
        min_point_size = 0

        for i in range(self.partitions_number):
            class_counts = [0] * self.num_classes
            indices = partitions_map[i]
            for idx in indices:
                label = dataset.targets[idx]
                class_counts[label] += 1

            # Normalize the point sizes for this partition, handling the case where max_samples_partition is 0
            max_samples_partition = max(class_counts)
            if max_samples_partition == 0:
                logging.warning(f"[{phase}] Participant {i} has no samples. Skipping size normalization.")
                sizes = [min_point_size] * self.num_classes
            else:
                sizes = [
                    (size / max_samples_partition) * (max_point_size - min_point_size) + min_point_size
                    for size in class_counts
                ]
            plt.scatter([i] * self.num_classes, range(self.num_classes), s=sizes, alpha=0.5)

        plt.xlabel("Participant")
        plt.ylabel("Class")
        plt.xticks(range(self.partitions_number))
        plt.yticks(range(self.num_classes))
        plt.title(
            f"[{phase}] Data distribution across participants ({'IID' if self.iid else f'Non-IID - {self.partition}'} - {self.partition_parameter})"
        )
        plt.tight_layout()

        path_to_save = f"{self.config_dir}/all_data_distribution_CIRCLES_{'iid' if self.iid else 'non_iid'}{'_' + self.partition if not self.iid else ''}_{phase}.pdf"
        plt.savefig(path_to_save, dpi=300, bbox_inches="tight")
        plt.close()
