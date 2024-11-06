import lightning as pl
import matplotlib
import matplotlib.pyplot as plt
import seaborn as sns
import torch
import torch.nn.functional as F
from torchmetrics import MetricCollection
from torchmetrics.classification import (
    MulticlassAccuracy,
    MulticlassConfusionMatrix,
    MulticlassF1Score,
    MulticlassPrecision,
    MulticlassRecall,
)

matplotlib.use("Agg")
plt.switch_backend("Agg")
import logging

from nebula.config.config import TRAINING_LOGGER

logging_training = logging.getLogger(TRAINING_LOGGER)


class ContrastiveLoss(torch.nn.Module):
    """
    Contrastive loss function.
    """

    def __init__(self, mu=0.5):
        super().__init__()
        self.mu = mu
        self.cross_entropy_loss = torch.nn.CrossEntropyLoss()

    def forward(self, local_out, global_out, historical_out, labels):
        """
        Calculates the contrastive loss between the local output, global output, and historical output.

        Args:
            local_out (torch.Tensor): The local output tensor of shape (batch_size, embedding_size).
            global_out (torch.Tensor): The global output tensor of shape (batch_size, embedding_size).
            historical_out (torch.Tensor): The historical output tensor of shape (batch_size, embedding_size).
            labels (torch.Tensor): The ground truth labels tensor of shape (batch_size,).

        Returns:
            torch.Tensor: The contrastive loss value.

        Raises:
            ValueError: If the input tensors have different shapes.

        Notes:
            - The contrastive loss is calculated as the difference between the mean cosine similarity of the local output
                with the historical output and the mean cosine similarity of the local output with the global output,
                multiplied by a scaling factor mu.
            - The cosine similarity values represent the similarity between the corresponding vectors in the input tensors.
            Higher values indicate greater similarity, while lower values indicate less similarity.
        """
        if local_out.shape != global_out.shape or local_out.shape != historical_out.shape:
            raise ValueError("Input tensors must have the same shape.")

        # Cross-entropy loss
        ce_loss = self.cross_entropy_loss(local_out, labels)
        # if round > 1:
        # Positive cosine similarity
        pos_cos_sim = F.cosine_similarity(local_out, historical_out, dim=1).mean()

        # Negative cosine similarity
        neg_cos_sim = -F.cosine_similarity(local_out, global_out, dim=1).mean()

        # Combined loss
        contrastive_loss = ce_loss + self.mu * 0.5 * (pos_cos_sim + neg_cos_sim)

        logging_training.debug(
            f"Contrastive loss (mu={self.mu}) with 0.5 of factor: ce_loss: {ce_loss}, pos_cos_sim_local_historical: {pos_cos_sim}, neg_cos_sim_local_global: {neg_cos_sim}, loss: {contrastive_loss}"
        )
        return contrastive_loss
        # else:
        #    logging_training.debug(f"Cross-entropy loss (local model): {ce_loss}")
        #    return ce_loss


class DualAggModel(pl.LightningModule):
    def process_metrics(self, phase, y_pred, y, loss=None, mode="local"):
        """
        Calculate and log metrics for the given phase.
        Args:
            phase (str): One of 'Train', 'Validation', or 'Test'
            y_pred (torch.Tensor): Model predictions
            y (torch.Tensor): Ground truth labels
            loss (torch.Tensor, optional): Loss value
        """

        y_pred_classes = torch.argmax(y_pred, dim=1)
        if phase == "Train":
            if mode == "local":
                output = self.local_train_metrics(y_pred_classes, y)
            elif mode == "historical":
                output = self.historical_train_metrics(y_pred_classes, y)
            elif mode == "global":
                output = self.global_train_metrics(y_pred_classes, y)
        elif phase == "Validation":
            if mode == "local":
                output = self.local_val_metrics(y_pred_classes, y)
            elif mode == "historical":
                output = self.historical_val_metrics(y_pred_classes, y)
            elif mode == "global":
                output = self.global_val_metrics(y_pred_classes, y)
        elif phase == "Test":
            if mode == "local":
                output = self.local_test_metrics(y_pred_classes, y)
            elif mode == "historical":
                output = self.historical_test_metrics(y_pred_classes, y)
            elif mode == "global":
                output = self.global_test_metrics(y_pred_classes, y)
        else:
            raise NotImplementedError
        # print(f"y_pred shape: {y_pred.shape}, y_pred_classes shape: {y_pred_classes.shape}, y shape: {y.shape}")  # Debug print
        output = {
            f"{mode}/{phase}/{key.replace('Multiclass', '').split('/')[-1]}": value for key, value in output.items()
        }
        self.log_dict(output, prog_bar=True, logger=True)

        if self.local_cm is not None and self.historical_cm is not None and self.global_cm is not None:
            if mode == "local":
                self.local_cm.update(y_pred_classes, y)
            elif mode == "historical":
                self.historical_cm.update(y_pred_classes, y)
            elif mode == "global":
                self.global_cm.update(y_pred_classes, y)

    def log_metrics_by_epoch(self, phase, print_cm=False, plot_cm=False, mode="local"):
        """
        Log all metrics at the end of an epoch for the given phase.
        Args:
            phase (str): One of 'Train', 'Validation', or 'Test'
            :param phase:
            :param plot_cm:
        """
        if mode == "local":
            print(f"Epoch end: {mode} {phase}, epoch number: {self.local_epoch_global_number[phase]}")
        elif mode == "historical":
            print(f"Epoch end: {mode} {phase}, epoch number: {self.historical_epoch_global_number[phase]}")
        elif mode == "global":
            print(f"Epoch end: {mode} {phase}, epoch number: {self.global_epoch_global_number[phase]}")

        if phase == "Train":
            if mode == "local":
                output = self.local_train_metrics.compute()
                self.local_train_metrics.reset()
            elif mode == "historical":
                output = self.historical_train_metrics.compute()
                self.historical_train_metrics.reset()
            elif mode == "global":
                output = self.global_train_metrics.compute()
                self.global_train_metrics.reset()
        elif phase == "Validation":
            if mode == "local":
                output = self.local_val_metrics.compute()
                self.local_val_metrics.reset()
            elif mode == "historical":
                output = self.historical_val_metrics.compute()
                self.historical_val_metrics.reset()
            elif mode == "global":
                output = self.global_val_metrics.compute()
                self.global_val_metrics.reset()
        elif phase == "Test":
            if mode == "local":
                output = self.local_test_metrics.compute()
                self.local_test_metrics.reset()
            elif mode == "historical":
                output = self.historical_test_metrics.compute()
                self.historical_test_metrics.reset()
            elif mode == "global":
                output = self.global_test_metrics.compute()
                self.global_test_metrics.reset()
        else:
            raise NotImplementedError

        output = {
            f"{mode}/{phase}Epoch/{key.replace('Multiclass', '').split('/')[-1]}": value
            for key, value in output.items()
        }

        self.log_dict(output, prog_bar=True, logger=True)

        if self.local_cm is not None and self.historical_cm is not None and self.global_cm is not None:
            if mode == "local":
                cm = self.local_cm.compute().cpu()
            elif mode == "historical":
                cm = self.historical_cm.compute().cpu()
            elif mode == "global":
                cm = self.global_cm.compute().cpu()
            print(f"{mode}/{phase}Epoch/CM\n", cm) if print_cm else None
            if plot_cm:
                plt.figure(figsize=(10, 7))
                ax = sns.heatmap(cm.numpy(), annot=True, fmt="d", cmap="Blues")
                ax.set_xlabel("Predicted labels")
                ax.set_ylabel("True labels")
                ax.set_title("Confusion Matrix")
                ax.set_xticks(range(self.num_classes))
                ax.set_yticks(range(self.num_classes))
                ax.xaxis.set_ticklabels([i for i in range(self.num_classes)])
                ax.yaxis.set_ticklabels([i for i in range(self.num_classes)])
                if mode == "local":
                    self.logger.experiment.add_figure(
                        f"{mode}/{phase}Epoch/CM",
                        ax.get_figure(),
                        global_step=self.local_epoch_global_number[phase],
                    )
                elif mode == "historical":
                    self.logger.experiment.add_figure(
                        f"{mode}/{phase}Epoch/CM",
                        ax.get_figure(),
                        global_step=self.historical_epoch_global_number[phase],
                    )
                elif mode == "global":
                    self.logger.experiment.add_figure(
                        f"{mode}/{phase}Epoch/CM",
                        ax.get_figure(),
                        global_step=self.global_epoch_global_number[phase],
                    )
                plt.close()

        if mode == "local":
            self.local_epoch_global_number[phase] += 1
        elif mode == "historical":
            self.historical_epoch_global_number[phase] += 1
        elif mode == "global":
            self.global_epoch_global_number[phase] += 1

    def __init__(
        self,
        input_channels=3,
        num_classes=10,
        learning_rate=1e-3,
        mu=0.5,
        metrics=None,
        confusion_matrix=None,
        seed=None,
    ):
        super().__init__()

        self.input_channels = input_channels
        self.num_classes = num_classes
        self.learning_rate = learning_rate
        self.mu = mu

        if metrics is None:
            metrics = MetricCollection([
                MulticlassAccuracy(num_classes=num_classes),
                MulticlassPrecision(num_classes=num_classes),
                MulticlassRecall(num_classes=num_classes),
                MulticlassF1Score(num_classes=num_classes),
            ])

        # Define metrics
        self.local_train_metrics = metrics.clone(prefix="Local/Train/")
        self.local_val_metrics = metrics.clone(prefix="Local/Validation/")
        self.local_test_metrics = metrics.clone(prefix="Local/Test/")

        self.historical_train_metrics = metrics.clone(prefix="Historical/Train/")
        self.historical_val_metrics = metrics.clone(prefix="Historical/Validation/")
        self.historical_test_metrics = metrics.clone(prefix="Historical/Test/")

        self.global_train_metrics = metrics.clone(prefix="Global/Train/")
        self.global_val_metrics = metrics.clone(prefix="Global/Validation/")
        self.global_test_metrics = metrics.clone(prefix="Global/Test/")

        if confusion_matrix is None:
            self.local_cm = MulticlassConfusionMatrix(num_classes=num_classes)
            self.historical_cm = MulticlassConfusionMatrix(num_classes=num_classes)
            self.global_cm = MulticlassConfusionMatrix(num_classes=num_classes)

        # Set seed for reproducibility initialization
        if seed is not None:
            torch.manual_seed(seed)
            torch.cuda.manual_seed_all(seed)

        self.local_epoch_global_number = {"Train": 0, "Validation": 0, "Test": 0}
        self.historical_epoch_global_number = {"Train": 0, "Validation": 0, "Test": 0}
        self.global_epoch_global_number = {"Train": 0, "Validation": 0, "Test": 0}

        self.config = {"beta1": 0.851436, "beta2": 0.999689, "amsgrad": True}

        self.example_input_array = torch.rand(1, 3, 32, 32)
        self.learning_rate = learning_rate
        self.criterion = ContrastiveLoss(mu=self.mu)

        # Define layers of the model
        self.model = torch.nn.Sequential(
            torch.nn.Conv2d(input_channels, 16, 3, padding=1),
            torch.nn.ReLU(),
            torch.nn.MaxPool2d(2, 2),
            torch.nn.Conv2d(16, 32, 3, padding=1),
            torch.nn.ReLU(),
            torch.nn.MaxPool2d(2, 2),
            torch.nn.Conv2d(32, 64, 3, padding=1),
            torch.nn.ReLU(),
            torch.nn.MaxPool2d(2, 2),
            torch.nn.Flatten(),
            torch.nn.Linear(64 * 4 * 4, 512),
            torch.nn.ReLU(),
            torch.nn.Linear(512, num_classes),
        )

        # Siamese models of the model above
        self.historical_model = torch.nn.Sequential(
            torch.nn.Conv2d(input_channels, 16, 3, padding=1),
            torch.nn.ReLU(),
            torch.nn.MaxPool2d(2, 2),
            torch.nn.Conv2d(16, 32, 3, padding=1),
            torch.nn.ReLU(),
            torch.nn.MaxPool2d(2, 2),
            torch.nn.Conv2d(32, 64, 3, padding=1),
            torch.nn.ReLU(),
            torch.nn.MaxPool2d(2, 2),
            torch.nn.Flatten(),
            torch.nn.Linear(64 * 4 * 4, 512),
            torch.nn.ReLU(),
            torch.nn.Linear(512, num_classes),
        )
        self.global_model = torch.nn.Sequential(
            torch.nn.Conv2d(input_channels, 16, 3, padding=1),
            torch.nn.ReLU(),
            torch.nn.MaxPool2d(2, 2),
            torch.nn.Conv2d(16, 32, 3, padding=1),
            torch.nn.ReLU(),
            torch.nn.MaxPool2d(2, 2),
            torch.nn.Conv2d(32, 64, 3, padding=1),
            torch.nn.ReLU(),
            torch.nn.MaxPool2d(2, 2),
            torch.nn.Flatten(),
            torch.nn.Linear(64 * 4 * 4, 512),
            torch.nn.ReLU(),
            torch.nn.Linear(512, num_classes),
        )
        # self.historical_model = copy.deepcopy(self.model)
        # self.global_model = copy.deepcopy(self.model)

    def forward(self, x, mode="local"):
        """Forward pass of the model."""
        if mode == "local":
            return self.model(x)
        elif mode == "global":
            return self.global_model(x)
        elif mode == "historical":
            return self.historical_model(x)
        else:
            raise NotImplementedError

    def configure_optimizers(self):
        """ """
        optimizer = torch.optim.Adam(
            self.parameters(),
            lr=self.learning_rate,
            betas=(self.config["beta1"], self.config["beta2"]),
            amsgrad=self.config["amsgrad"],
        )
        return optimizer

    def step(self, batch, batch_idx, phase):
        images, labels = batch
        images = images.to(self.device)
        labels = labels.to(self.device)
        local_out = self.forward(images, mode="local")
        with torch.no_grad():
            historical_out = self.forward(images, mode="historical")
            global_out = self.forward(images, mode="global")

        loss = self.criterion(local_out, global_out, historical_out, labels)

        # Get metrics for each batch and log them
        self.log(f"{phase}/ConstrastiveLoss", loss, prog_bar=True, logger=True)  # Constrastive loss
        self.process_metrics(phase, local_out, labels, loss, mode="local")
        self.process_metrics(phase, historical_out, labels, loss, mode="historical")
        self.process_metrics(phase, global_out, labels, loss, mode="global")

        return loss

    def training_step(self, batch, batch_id):
        """
        Training step for the model.
        Args:
            batch:
            batch_id:

        Returns:
        """
        return self.step(batch, batch_id, "Train")

    def on_train_epoch_end(self):
        self.log_metrics_by_epoch("Train", print_cm=True, plot_cm=True, mode="local")
        self.log_metrics_by_epoch("Train", print_cm=True, plot_cm=True, mode="historical")
        self.log_metrics_by_epoch("Train", print_cm=True, plot_cm=True, mode="global")

    def validation_step(self, batch, batch_idx):
        """
        Validation step for the model.
        Args:
            batch:
            batch_idx:

        Returns:
        """
        return self.step(batch, batch_idx, "Validation")

    def on_validation_epoch_end(self):
        self.log_metrics_by_epoch("Validation", print_cm=True, plot_cm=False, mode="local")
        self.log_metrics_by_epoch("Validation", print_cm=True, plot_cm=False, mode="historical")
        self.log_metrics_by_epoch("Validation", print_cm=True, plot_cm=False, mode="global")

    def test_step(self, batch, batch_idx):
        """
        Test step for the model.
        Args:
            batch:
            batch_idx:

        Returns:
        """
        return self.step(batch, batch_idx, "Test")

    def on_test_epoch_end(self):
        self.log_metrics_by_epoch("Test", print_cm=True, plot_cm=True, mode="local")
        self.log_metrics_by_epoch("Test", print_cm=True, plot_cm=True, mode="historical")
        self.log_metrics_by_epoch("Test", print_cm=True, plot_cm=True, mode="global")

    def save_historical_model(self):
        """
        Save the current local model as the historical model.
        """
        logging_training.info("Copying local model to historical model.")
        self.historical_model.load_state_dict(self.model.state_dict())

    def global_load_state_dict(self, state_dict):
        """
        Load the given state dictionary into the global model.
        Args:
            state_dict (dict): The state dictionary to load into the global model.
        """
        logging_training.info("Loading state dict into global model.")
        adapted_state_dict = self.adapt_state_dict_for_model(state_dict, "model")
        self.global_model.load_state_dict(adapted_state_dict)

    def historical_load_state_dict(self, state_dict):
        """
        Load the given state dictionary into the historical model.
        Args:
            state_dict (dict): The state dictionary to load into the historical model.
        """
        logging_training.info("Loading state dict into historical model.")
        adapted_state_dict = self.adapt_state_dict_for_model(state_dict, "model")
        self.historical_model.load_state_dict(adapted_state_dict)

    def adapt_state_dict_for_model(self, state_dict, model_prefix):
        """
        Adapt the keys in the provided state_dict to match the structure expected by the model.
        """
        new_state_dict = {}
        prefix = f"{model_prefix}."
        for key, value in state_dict.items():
            if key.startswith(prefix):
                # Remove the specific prefix from each key
                new_key = key[len(prefix) :]
                new_state_dict[new_key] = value
        return new_state_dict

    def get_global_model_parameters(self):
        """
        Get the parameters of the global model.
        """
        return self.global_model.state_dict()

    def print_summary(self):
        """
        Print a summary of local, historical and global models to check if they are the same.
        """
        logging_training.info("Local model summary:")
        logging_training.info(self.model)
        logging_training.info("Historical model summary:")
        logging_training.info(self.historical_model)
        logging_training.info("Global model summary:")
        logging_training.info(self.global_model)
