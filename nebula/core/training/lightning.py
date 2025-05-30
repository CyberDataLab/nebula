import asyncio
import copy
import gc
import gzip
import hashlib
import io
import logging
import os
import pickle
import traceback
from collections import OrderedDict

import torch
from lightning import Trainer
from lightning.pytorch.callbacks import ModelSummary, ProgressBar
from lightning.pytorch.loggers import CSVLogger
from torch.nn import functional as F

from nebula.config.config import TRAINING_LOGGER
from nebula.core.utils.deterministic import enable_deterministic
from nebula.core.utils.nebulalogger_tensorboard import NebulaTensorBoardLogger
from nebula.core.nebulaevents import TestMetricsEvent
from nebula.core.eventmanager import EventManager

logging_training = logging.getLogger(TRAINING_LOGGER)


class NebulaProgressBar(ProgressBar):
    """Nebula progress bar for training.
    Logs the percentage of completion of the training process using logging.
    """

    def __init__(self, log_every_n_steps=100):
        super().__init__()
        self.enable = True
        self.log_every_n_steps = log_every_n_steps

    def enable(self):
        """Enable progress bar logging."""
        self.enable = True

    def disable(self):
        """Disable the progress bar logging."""
        self.enable = False

    def on_train_epoch_start(self, trainer, pl_module):
        """Called when the training epoch starts."""
        super().on_train_epoch_start(trainer, pl_module)
        if self.enable:
            logging_training.info(f"Starting Epoch {trainer.current_epoch}")

    def on_train_batch_end(self, trainer, pl_module, outputs, batch, batch_idx):
        """Called at the end of each training batch."""
        super().on_train_batch_end(trainer, pl_module, outputs, batch, batch_idx)
        if self.enable:
            if (batch_idx + 1) % self.log_every_n_steps == 0 or (batch_idx + 1) == self.total_train_batches:
                # Calculate percentage complete for the current epoch
                percent = ((batch_idx + 1) / self.total_train_batches) * 100  # +1 to count current batch
                logging_training.info(f"Epoch {trainer.current_epoch} - {percent:.01f}% complete")

    def on_train_epoch_end(self, trainer, pl_module):
        """Called at the end of the training epoch."""
        super().on_train_epoch_end(trainer, pl_module)
        if self.enable:
            logging_training.info(f"Epoch {trainer.current_epoch} finished")

    def on_validation_epoch_start(self, trainer, pl_module):
        super().on_validation_epoch_start(trainer, pl_module)
        if self.enable:
            logging_training.info(f"Starting validation for Epoch {trainer.current_epoch}")

    def on_validation_epoch_end(self, trainer, pl_module):
        super().on_validation_epoch_end(trainer, pl_module)
        if self.enable:
            logging_training.info(f"Validation for Epoch {trainer.current_epoch} finished")

    def on_test_batch_start(self, trainer, pl_module, batch, batch_idx, dataloader_idx):
        super().on_test_batch_start(trainer, pl_module, batch, batch_idx, dataloader_idx)
        if not self.has_dataloader_changed(dataloader_idx):
            return

    def on_test_batch_end(self, trainer, pl_module, outputs, batch, batch_idx, dataloader_idx):
        """Called at the end of each test batch."""
        super().on_test_batch_end(trainer, pl_module, outputs, batch, batch_idx, dataloader_idx)
        if self.enable:
            total_batches = self.total_test_batches_current_dataloader
            if total_batches == 0:
                logging_training.warning(
                    f"Total test batches is 0 for dataloader {dataloader_idx}, cannot compute progress."
                )
                return

            if (batch_idx + 1) % self.log_every_n_steps == 0 or (batch_idx + 1) == total_batches:
                percent = ((batch_idx + 1) / total_batches) * 100  # +1 to count the current batch
                logging_training.info(
                    f"Test Epoch {trainer.current_epoch}, Dataloader {dataloader_idx} - {percent:.01f}% complete"
                )

    def on_test_epoch_start(self, trainer, pl_module):
        super().on_test_epoch_start(trainer, pl_module)
        if self.enable:
            logging_training.info(f"Starting testing for Epoch {trainer.current_epoch}")

    def on_test_epoch_end(self, trainer, pl_module):
        super().on_test_epoch_end(trainer, pl_module)
        if self.enable:
            logging_training.info(f"Testing for Epoch {trainer.current_epoch} finished")


class ParameterSerializeError(Exception):
    """Custom exception for errors setting model parameters."""


class ParameterDeserializeError(Exception):
    """Custom exception for errors setting model parameters."""


class ParameterSettingError(Exception):
    """Custom exception for errors setting model parameters."""


class Lightning:
    DEFAULT_MODEL_WEIGHT = 1
    BYPASS_MODEL_WEIGHT = 0

    def __init__(self, model, datamodule, config=None):
        # self.model = torch.compile(model, mode="reduce-overhead")
        self.model = model
        self.datamodule = datamodule
        self.config = config
        self._trainer = None
        self.epochs = 1
        self.round = 0
        self.experiment_name = self.config.participant["scenario_args"]["name"]
        self.idx = self.config.participant["device_args"]["idx"]
        self.log_dir = os.path.join(self.config.participant["tracking_args"]["log_dir"], self.experiment_name)
        self._logger = None
        self.create_logger()
        enable_deterministic(seed=self.config.participant["scenario_args"]["random_seed"])

    @property
    def logger(self):
        return self._logger

    def get_round(self):
        return self.round

    def set_model(self, model):
        self.model = model

    def set_datamodule(self, datamodule):
        self.datamodule = datamodule

    def create_logger(self):
        if self.config.participant["tracking_args"]["local_tracking"] == "csv":
            nebulalogger = CSVLogger(f"{self.log_dir}", name="metrics", version=f"participant_{self.idx}")
        elif self.config.participant["tracking_args"]["local_tracking"] == "basic":
            logger_config = None
            if self._logger is not None:
                logger_config = self._logger.get_logger_config()
            nebulalogger = NebulaTensorBoardLogger(
                self.config.participant["scenario_args"]["start_time"],
                f"{self.log_dir}",
                name="metrics",
                version=f"participant_{self.idx}",
                log_graph=False,
            )
            # Restore logger configuration
            nebulalogger.set_logger_config(logger_config)
        else:
            nebulalogger = None

        self._logger = nebulalogger

    def create_trainer(self):
        # Create a new trainer and logger for each round
        self.create_logger()
        num_gpus = len(self.config.participant["device_args"]["gpu_id"])
        if self.config.participant["device_args"]["accelerator"] == "gpu" and num_gpus > 0:
            # Use all available GPUs
            if num_gpus > 1:
                gpu_index = [self.config.participant["device_args"]["idx"] % num_gpus]
            # Use the selected GPU
            else:
                gpu_index = self.config.participant["device_args"]["gpu_id"]
            logging_training.info(f"Creating trainer with accelerator GPU ({gpu_index})")
            self._trainer = Trainer(
                callbacks=[ModelSummary(max_depth=1), NebulaProgressBar()],
                max_epochs=self.epochs,
                accelerator="gpu",
                devices=gpu_index,
                logger=self._logger,
                enable_checkpointing=False,
                enable_model_summary=False,
                # deterministic=True
            )
        else:
            logging_training.info("Creating trainer with accelerator CPU")
            self._trainer = Trainer(
                callbacks=[ModelSummary(max_depth=1), NebulaProgressBar()],
                max_epochs=self.epochs,
                accelerator="cpu",
                devices="auto",
                logger=self._logger,
                enable_checkpointing=False,
                enable_model_summary=False,
                # deterministic=True
            )
        logging_training.info(f"Trainer strategy: {self._trainer.strategy}")

    def validate_neighbour_model(self, neighbour_model_param):
        avg_loss = 0
        running_loss = 0
        bootstrap_dataloader = self.datamodule.bootstrap_dataloader()
        num_samples = 0
        neighbour_model = copy.deepcopy(self.model)
        neighbour_model.load_state_dict(neighbour_model_param)

        # enable evaluation mode, prevent memory leaks.
        # no need to switch back to training since model is not further used.
        if torch.cuda.is_available():
            neighbour_model = neighbour_model.to("cuda")
        neighbour_model.eval()

        # bootstrap_dataloader = bootstrap_dataloader.to('cuda')
        with torch.no_grad():
            for inputs, labels in bootstrap_dataloader:
                if torch.cuda.is_available():
                    inputs = inputs.to("cuda")
                    labels = labels.to("cuda")
                outputs = neighbour_model(inputs)
                loss = F.cross_entropy(outputs, labels)
                running_loss += loss.item()
                num_samples += inputs.size(0)

        avg_loss = running_loss / len(bootstrap_dataloader)
        logging_training.info(f"Computed neighbor loss over {num_samples} data samples")
        return avg_loss

    def get_hash_model(self):
        """
        Returns:
            str: SHA256 hash of model parameters
        """
        return hashlib.sha256(self.serialize_model(self.model)).hexdigest()

    def set_epochs(self, epochs):
        self.epochs = epochs

    def set_current_round(self, round):
        logging.info(f"Update | current round = {round}")
        self.round = round
        self.model.set_updated_round(round)

    def get_current_loss(self):
        return self.model.get_loss()

    def serialize_model(self, model):
        # From https://pytorch.org/docs/stable/notes/serialization.html
        try:
            buffer = io.BytesIO()
            with gzip.GzipFile(fileobj=buffer, mode="wb") as f:
                torch.save(model, f, pickle_protocol=pickle.HIGHEST_PROTOCOL)
            serialized_data = buffer.getvalue()
            buffer.close()
            del buffer
            return serialized_data
        except Exception as e:
            raise ParameterSerializeError("Error serializing model") from e

    def deserialize_model(self, data):
        # From https://pytorch.org/docs/stable/notes/serialization.html
        try:
            buffer = io.BytesIO(data)
            with gzip.GzipFile(fileobj=buffer, mode="rb") as f:
                params_dict = torch.load(f)
            buffer.close()
            del buffer
            return OrderedDict(params_dict)
        except Exception as e:
            raise ParameterDeserializeError("Error decoding parameters") from e

    def set_model_parameters(self, params, initialize=False):
        try:
            self.model.load_state_dict(params)
        except Exception as e:
            raise ParameterSettingError("Error setting parameters") from e

    def get_model_parameters(self, bytes=False, initialize=False):
        if bytes:
            return self.serialize_model(self.model.state_dict())
        return self.model.state_dict()

    async def train(self):
        try:
            self.create_trainer()
            logging.info(f"{'=' * 10} [Training] Started (check training logs for progress) {'=' * 10}")
            await asyncio.to_thread(self._train_sync)
            logging.info(f"{'=' * 10} [Training] Finished (check training logs for progress) {'=' * 10}")
        except Exception as e:
            logging_training.error(f"Error training model: {e}")
            logging_training.error(traceback.format_exc())

    def _train_sync(self):
        try:
            self._trainer.fit(self.model, self.datamodule)
        except Exception as e:
            logging_training.error(f"Error in _train_sync: {e}")
            tb = traceback.format_exc()
            logging_training.error(f"Traceback: {tb}")
            # If "raise", the exception will be managed by the main thread

    async def test(self):
        try:
            self.create_trainer()
            logging.info(f"{'=' * 10} [Testing] Started (check training logs for progress) {'=' * 10}")
            loss, accuracy = await asyncio.to_thread(self._test_sync)
            logging.info(f"{'=' * 10} [Testing] Finished (check training logs for progress) {'=' * 10}")
            tme = TestMetricsEvent(loss, accuracy)
            await EventManager.get_instance().publish_addonevent(tme)
        except Exception as e:
            logging_training.error(f"Error testing model: {e}")
            logging_training.error(traceback.format_exc())

    def _test_sync(self):
        try:
            self._trainer.test(self.model, self.datamodule, verbose=True)
            metrics = self._trainer.callback_metrics
            loss = metrics.get('val_loss/dataloader_idx_0', None).item()
            accuracy = metrics.get('val_accuracy/dataloader_idx_0', None).item()
            return loss, accuracy
        except Exception as e:
            logging_training.error(f"Error in _test_sync: {e}")
            tb = traceback.format_exc()
            logging_training.error(f"Traceback: {tb}")
            # If "raise", the exception will be managed by the main thread
            return None, None

    def cleanup(self):
        if self._trainer is not None:
            self._trainer._teardown()
            del self._trainer
        if self.datamodule is not None:
            self.datamodule.teardown()
        gc.collect()
        torch.cuda.empty_cache()

    def get_model_weight(self):
        weight = self.datamodule.model_weight
        if weight is None:
            raise ValueError("Model weight not set. Please call setup('fit') before requesting model weight.")
        return weight

    def on_round_start(self):
        self.datamodule.setup()
        self._logger.log_data({"A-Round": self.round})
        # self.reporter.enqueue_data("Round", self.round)

    def on_round_end(self):
        self._logger.global_step = self._logger.global_step + self._logger.local_step
        self._logger.local_step = 0
        self.round += 1
        self.model.on_round_end()
        logging.info("Flushing memory cache at the end of round...")
        self.cleanup()

    def on_learning_cycle_end(self):
        self._logger.log_data({"A-Round": self.round})
        # self.reporter.enqueue_data("Round", self.round)

    def update_model_learning_rate(self, new_lr):
        self.model.modify_learning_rate(new_lr)

    def show_current_learning_rate(self):
        self.model.show_current_learning_rate()
