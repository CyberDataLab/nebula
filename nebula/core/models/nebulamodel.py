import logging
from abc import ABC, abstractmethod

import lightning as pl
import matplotlib
import matplotlib.pyplot as plt
import seaborn as sns
import torch
from torchmetrics import MetricCollection
from torchmetrics.classification import (
    MulticlassAccuracy,
    MulticlassConfusionMatrix,
    MulticlassF1Score,
    MulticlassPrecision,
    MulticlassRecall,
)

from nebula.addons.functions import print_msg_box

matplotlib.use("Agg")
plt.switch_backend("Agg")
from nebula.config.config import TRAINING_LOGGER

logging_training = logging.getLogger(TRAINING_LOGGER)


class NebulaModel(pl.LightningModule, ABC):
    """
    Abstract class for the NEBULA model.

    This class is an abstract class that defines the interface for the NEBULA model.
    """

    def process_metrics(self, phase, y_pred, y, loss=None):
        """
        Calculate and log metrics for the given phase.
        The metrics are calculated in each batch.
        Args:
            phase (str): One of 'Train', 'Validation', or 'Test'
            y_pred (torch.Tensor): Model predictions
            y (torch.Tensor): Ground truth labels
            loss (torch.Tensor, optional): Loss value
        """

        y_pred_classes = torch.argmax(y_pred, dim=1).detach()
        y = y.detach()
        if phase == "Train":
            self.logger.log_data({f"{phase}/Loss": loss.detach()})
            self.train_metrics.update(y_pred_classes, y)
        elif phase == "Validation":
            self.val_metrics.update(y_pred_classes, y)
        elif phase == "Test (Local)":
            self.test_metrics.update(y_pred_classes, y)
            self.cm.update(y_pred_classes, y) if self.cm is not None else None
        elif phase == "Test (Global)":
            self.test_metrics_global.update(y_pred_classes, y)
            self.cm_global.update(y_pred_classes, y) if self.cm_global is not None else None
        else:
            raise NotImplementedError

        del y_pred_classes, y

    def log_metrics_end(self, phase):
        """
        Log metrics for the given phase.
        Args:
            phase (str): One of 'Train', 'Validation', 'Test (Local)', or 'Test (Global)'
            print_cm (bool): Print confusion matrix
            plot_cm (bool): Plot confusion matrix
        """
        if phase == "Train":
            output = self.train_metrics.compute()
        elif phase == "Validation":
            output = self.val_metrics.compute()
        elif phase == "Test (Local)":
            output = self.test_metrics.compute()
        elif phase == "Test (Global)":
            output = self.test_metrics_global.compute()
        else:
            raise NotImplementedError

        output = {
            f"{phase}/{key.replace('Multiclass', '').split('/')[-1]}": value.detach() for key, value in output.items()
        }

        output_values = {
            key: float(value.detach().cpu().item()) for key, value in output.items()
        }

        if phase == "Train":
            self._latest_train_metrics = output_values

        if phase == "Validation":
            self._latest_validation_metrics = output_values

        if phase in {"Test", "Test (Local)"}:
            self._latest_test_metrics = output_values

        if phase == "Train" and self._train_extra_metrics:
            output.update({
                f"{phase}/{key}": torch.tensor(value["sum"] / value["count"], device=self.device)
                for key, value in self._train_extra_metrics.items()
                if value["count"] > 0
            })

        self.logger.log_data(output, step=self.global_number[phase])

        metrics_str = ""
        for key, value in output.items():
            metrics_str += f"{key}: {value:.4f}\n"
        print_msg_box(
            metrics_str,
            indent=2,
            title=f"{phase} Metrics | Epoch: {self.global_number[phase]} | Round: {self.round}",
            logger_name=TRAINING_LOGGER,
        )

    def generate_confusion_matrix(self, phase, print_cm=False, plot_cm=False):
        """
        Generate and plot the confusion matrix for the given phase.
        Args:
            phase (str): One of 'Train', 'Validation', 'Test (Local)', or 'Test (Global)'
        """
        if phase == "Test (Local)":
            if self.cm is None:
                raise ValueError(f"Confusion matrix not available for {phase} phase.")
            cm = self.cm.compute().cpu()
        elif phase == "Test (Global)":
            if self.cm_global is None:
                raise ValueError(f"Confusion matrix not available for {phase} phase.")
            cm = self.cm_global.compute().cpu()
        else:
            raise NotImplementedError

        if print_cm:
            logging_training.info(f"{phase} / Confusion Matrix:\n{cm}")

        if plot_cm:
            cm_numpy = cm.numpy().astype(int)
            classes = [i for i in range(self.num_classes)]
            fig, ax = plt.subplots(figsize=(12, 12))
            sns.heatmap(
                cm_numpy,
                annot=False,
                fmt="",
                cmap="Blues",
                ax=ax,
                xticklabels=classes,
                yticklabels=classes,
                square=True,
            )
            ax.set_xlabel("Predicted labels", fontsize=12)
            ax.set_ylabel("True labels", fontsize=12)
            ax.set_title(f"{phase} Confusion Matrix", fontsize=16)
            plt.xticks(rotation=90, fontsize=6)
            plt.yticks(rotation=0, fontsize=6)
            plt.tight_layout()
            self.logger.log_figure(fig, step=self.round, name=f"{phase}/CM")
            plt.close()

            del cm_numpy, classes, fig, ax

        if phase == "Test (Local)":
            self.cm.reset()
        else:
            self.cm_global.reset()

        del cm

    def __init__(
        self,
        input_channels=1,
        num_classes=10,
        learning_rate=1e-3,
        metrics=None,
        confusion_matrix=None,
        seed=None,
    ):
        super().__init__()

        self.input_channels = input_channels
        self.num_classes = num_classes
        self.learning_rate = learning_rate

        if metrics is None:
            metrics = MetricCollection([
                MulticlassAccuracy(num_classes=num_classes),
                MulticlassPrecision(num_classes=num_classes),
                MulticlassRecall(num_classes=num_classes),
                MulticlassF1Score(num_classes=num_classes, average="macro"),
            ])
        self.train_metrics = metrics.clone(prefix="Train/")
        self.val_metrics = metrics.clone(prefix="Validation/")
        self.test_metrics = metrics.clone(prefix="Test (Local)/")
        self.test_metrics_global = metrics.clone(prefix="Test (Global)/")
        del metrics
        if confusion_matrix is None:
            self.cm = MulticlassConfusionMatrix(num_classes=num_classes)
            self.cm_global = MulticlassConfusionMatrix(num_classes=num_classes)
        if seed is not None:
            torch.manual_seed(seed)
            torch.cuda.manual_seed_all(seed)

        # Round counter (number of training-validation-test rounds)
        self.round = 0

        # Epochs counter
        self.global_number = {
            "Train": 0,
            "Validation": 0,
            "Test (Local)": 0,
            "Test (Global)": 0,
        }

        # Communication manager for sending messages from the model (e.g., prototypes, gradients)
        # Model parameters are sent by default using network.propagator
        self.communication_manager = None

        self._current_loss = -1
        self._optimizer = None
        self._optimizer_override = None
        self._latest_train_metrics = {}
        self._latest_validation_metrics = {}
        self._latest_test_metrics = {}
        self._train_extra_metrics = {}

        # DP trainers update these fields after querying the Opacus accountant.
        self.dp_enabled = False
        self.dp_epsilon = None
        self.dp_delta = None
        self.adversarial_training = None

    def set_optimizer_override(self, optimizer):
        self._optimizer_override = optimizer
        self._optimizer = optimizer

    def clear_optimizer_override(self):
        self._optimizer_override = None

    def get_optimizer_override(self):
        return self._optimizer_override

    def set_adversarial_training(self, adversarial_training):
        self.adversarial_training = adversarial_training

    def clear_adversarial_training(self):
        self.adversarial_training = None

    def set_communication_manager(self, communication_manager):
        self.communication_manager = communication_manager

    def get_communication_manager(self):
        if self.communication_manager is None:
            raise ValueError("Communication manager not set.")
        return self.communication_manager

    @abstractmethod
    def forward(self, x):
        """Forward pass of the model."""
        pass

    @abstractmethod
    def configure_optimizers(self):
        """Optimizer configuration."""
        pass

    def step(self, batch, batch_idx, phase):
        """Training/validation/test step."""
        x, y = batch
        extra_metrics = {}
        if phase == "Train" and self.adversarial_training is not None:
            loss, y_pred, extra_metrics = self.adversarial_training.compute_training_step(
                self,
                x,
                y,
                self.criterion,
            )
        else:
            y_pred = self.forward(x)
            loss = self.criterion(y_pred, y)

        self.process_metrics(phase, y_pred, y, loss)
        if phase == "Train" and extra_metrics:
            self._log_training_extra_metrics(extra_metrics)

        self._current_loss = loss
        return loss

    def _log_training_extra_metrics(self, metrics):
        if self.logger is None:
            return
        detached_metrics = {key: value.detach() for key, value in metrics.items()}
        for key, value in detached_metrics.items():
            metric = self._train_extra_metrics.setdefault(key, {"sum": 0.0, "count": 0})
            metric["sum"] += float(value.cpu().item())
            metric["count"] += 1
        self.logger.log_data({f"Train/{key}": value for key, value in detached_metrics.items()})

    def get_loss(self):
        return self._current_loss

    def get_latest_validation_metrics(self):
        return self._latest_validation_metrics

    def get_latest_train_metrics(self):
        return self._latest_train_metrics

    def get_latest_test_metrics(self):
        return self._latest_test_metrics

    def get_latest_train_accuracy(self):
        return self._latest_train_metrics.get("Train/Accuracy")

    def get_latest_test_macro_f1(self):
        return self._latest_test_metrics.get("Test (Local)/F1Score")

    def modify_learning_rate(self, new_lr):
        logging.info(f"Modifiying | learning rate, new value: {new_lr}")
        self.learning_rate = new_lr
        for param_group in self._optimizer.param_groups:
            param_group["lr"] = new_lr

    def show_current_learning_rate(self):
        for param_group in self._optimizer.param_groups:
            logging.info(f"Showing | Learning rate current value: {param_group['lr']}")

    def set_updated_round(self, round):
        self.round = round
        self.global_number = {
            "Train": round,
            "Validation": round,
            "Test (Local)": round,
            "Test (Global)": round,
        }

    def training_step(self, batch, batch_idx):
        """
        Training step for the model.
        Args:
            batch:
            batch_id:

        Returns:
        """
        return self.step(batch, batch_idx=batch_idx, phase="Train")

    def on_train_start(self):
        logging_training.info(f"{'=' * 10} [Training] Started {'=' * 10}")

    def on_train_end(self):
        logging_training.info(f"{'=' * 10} [Training] Done {'=' * 10}")

    def on_train_epoch_end(self):
        self.log_metrics_end("Train")
        self.train_metrics.reset()
        self._train_extra_metrics = {}
        self.global_number["Train"] += 1

    def validation_step(self, batch, batch_idx):
        """
        Validation step for the model.
        Args:
            batch:
            batch_idx:

        Returns:
        """
        return self.step(batch, batch_idx=batch_idx, phase="Validation")

    def on_validation_end(self):
        pass

    def on_validation_epoch_end(self):
        # In general, the validation phase is done in one epoch
        self.log_metrics_end("Validation")
        self.val_metrics.reset()
        self.global_number["Validation"] += 1

    def test_step(self, batch, batch_idx, dataloader_idx=None):
        """
        Test step for the model.
        Args:
            batch:
            batch_idx:

        Returns:
        """
        x, y = batch
        y_pred = self.forward(x)
        loss = self.criterion(y_pred, y)
        y_pred_classes = torch.argmax(y_pred, dim=1)
        accuracy = torch.mean((y_pred_classes == y).float())

        if dataloader_idx == 0:
            self.log(f"val_loss", loss, on_epoch=True, prog_bar=False)
            self.log(f"val_accuracy", accuracy, on_epoch=True, prog_bar=False)
            return self.step(batch, batch_idx=batch_idx, phase="Test (Local)")
        else:
            return self.step(batch, batch_idx=batch_idx, phase="Test (Global)")

    def on_test_start(self):
        logging_training.info(f"{'=' * 10} [Testing] Started {'=' * 10}")

    def on_test_end(self):
        logging_training.info(f"{'=' * 10} [Testing] Done {'=' * 10}")

    def on_test_epoch_end(self):
        # In general, the test phase is done in one epoch
        self.log_metrics_end("Test (Local)")
        self.log_metrics_end("Test (Global)")
        self.generate_confusion_matrix("Test (Local)", print_cm=True, plot_cm=True)
        self.generate_confusion_matrix("Test (Global)", print_cm=True, plot_cm=True)
        self.test_metrics.reset()
        self.test_metrics_global.reset()
        self.global_number["Test (Local)"] += 1
        self.global_number["Test (Global)"] += 1

    def on_round_end(self):
        self.round += 1


class NebulaModelStandalone(NebulaModel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    # Log metrics per epoch
    def on_train_end(self):
        pass

    def on_train_epoch_end(self):
        self.log_metrics_end("Train")
        self.train_metrics.reset()
        self._train_extra_metrics = {}
        # NebulaModel registers training rounds
        # NebulaModelStandalone register the global number of epochs instead of rounds
        self.global_number["Train"] += 1

    def on_validation_end(self):
        pass

    def on_validation_epoch_end(self):
        self.log_metrics_end("Validation")
        self.global_number["Validation"] += 1
        self.val_metrics.reset()

    def on_test_end(self):
        self.global_number["Test (Local)"] += 1
        self.global_number["Test (Global)"] += 1

    def on_test_epoch_end(self):
        self.log_metrics_end("Test (Local)")
        self.log_metrics_end("Test (Global)")
        self.generate_confusion_matrix("Test (Local)", print_cm=True, plot_cm=True)
        self.generate_confusion_matrix("Test (Global)", print_cm=True, plot_cm=True)
        self.test_metrics.reset()
        self.test_metrics_global.reset()
