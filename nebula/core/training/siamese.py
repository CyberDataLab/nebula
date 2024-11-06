import hashlib
import io
import logging
import traceback
from collections import OrderedDict

import torch
from lightning import Trainer
from lightning.pytorch.callbacks import RichModelSummary, RichProgressBar
from lightning.pytorch.callbacks.progress.rich_progress import RichProgressBarTheme

from nebula.core.utils.deterministic import enable_deterministic


class Siamese:
    def __init__(self, model, data, config=None, logger=None):
        # self.model = torch.compile(model, mode="reduce-overhead")
        self.model = model
        self.data = data
        self.config = config
        self.logger = logger
        self.__trainer = None
        self.epochs = 1
        logging.getLogger("lightning.pytorch").setLevel(logging.INFO)
        self.round = 0
        enable_deterministic(self.config)
        self.logger.log_data({"Round": self.round}, step=self.logger.global_step)

    @property
    def logger(self):
        return self._logger

    def get_round(self):
        return self.round

    def set_model(self, model):
        self.model = model

    def set_data(self, data):
        self.data = data

    def create_trainer(self):
        logging.info(
            "[Trainer] Creating trainer with accelerator: {}".format(
                self.config.participant["device_args"]["accelerator"]
            )
        )
        progress_bar = RichProgressBar(
            theme=RichProgressBarTheme(
                description="green_yellow",
                progress_bar="green1",
                progress_bar_finished="green1",
                progress_bar_pulse="#6206E0",
                batch_progress="green_yellow",
                time="grey82",
                processing_speed="grey82",
                metrics="grey82",
            ),
            leave=True,
        )
        if self.config.participant["device_args"]["accelerator"] == "gpu":
            # NEBULA uses 2 GPUs (max) to distribute the nodes.
            if self.config.participant["device_args"]["devices"] > 1:
                # If you have more than 2 GPUs, you should specify which ones to use.
                gpu_id = ([1] if self.config.participant["device_args"]["idx"] % 2 == 0 else [2],)
            else:
                # If there is only one GPU, it will be used.
                gpu_id = [1]

            self.__trainer = Trainer(
                callbacks=[RichModelSummary(max_depth=1), progress_bar],
                max_epochs=self.epochs,
                accelerator=self.config.participant["device_args"]["accelerator"],
                devices=gpu_id,
                logger=self.logger,
                log_every_n_steps=50,
                enable_checkpointing=False,
                enable_model_summary=False,
                enable_progress_bar=True,
                # deterministic=True
            )
        else:
            # NEBULA uses only CPU to distribute the nodes
            self.__trainer = Trainer(
                callbacks=[RichModelSummary(max_depth=1), progress_bar],
                max_epochs=self.epochs,
                accelerator=self.config.participant["device_args"]["accelerator"],
                devices="auto",
                logger=self.logger,
                log_every_n_steps=50,
                enable_checkpointing=False,
                enable_model_summary=False,
                enable_progress_bar=True,
                # deterministic=True
            )

    def get_global_model_parameters(self):
        return self.model.get_global_model_parameters()

    def set_parameter_second_aggregation(self, params):
        try:
            logging.info("Setting parameters in second aggregation...")
            self.model.load_state_dict(params)
        except:
            raise Exception("Error setting parameters")

    def get_model_parameters(self, bytes=False):
        if bytes:
            return self.serialize_model(self.model.state_dict())
        else:
            return self.model.state_dict()

    def get_hash_model(self):
        """
        Returns:
            str: SHA256 hash of model parameters
        """
        return hashlib.sha256(self.serialize_model()).hexdigest()

    def set_epochs(self, epochs):
        self.epochs = epochs

    ####
    # Model parameters serialization/deserialization
    # From https://pytorch.org/docs/stable/notes/serialization.html
    ####
    def serialize_model(self, model):
        try:
            buffer = io.BytesIO()
            # with gzip.GzipFile(fileobj=buffer, mode='wb') as f:
            #    torch.save(params, f)
            torch.save(model, buffer)
            return buffer.getvalue()
        except:
            raise Exception("Error serializing model")

    def deserialize_model(self, data):
        try:
            buffer = io.BytesIO(data)
            # with gzip.GzipFile(fileobj=buffer, mode='rb') as f:
            #    params_dict = torch.load(f, map_location='cpu')
            params_dict = torch.load(buffer, map_location="cpu")
            return OrderedDict(params_dict)
        except:
            raise Exception("Error decoding parameters")

    def set_model_parameters(self, params, initialize=False):
        try:
            if initialize:
                self.model.load_state_dict(params)
                self.model.global_load_state_dict(params)
                self.model.historical_load_state_dict(params)
            else:
                # First aggregation
                self.model.global_load_state_dict(params)
        except:
            raise Exception("Error setting parameters")

    def train(self):
        try:
            self.create_trainer()
            # torch.autograd.set_detect_anomaly(True)
            # TODO: It is necessary to train only the local model, save the history of the previous model and then load it, the global model is the aggregation of all the models.
            self.__trainer.fit(self.model, self.data)
            # Save local model as historical model (previous round)
            # It will be compared the next round during training local model (constrantive loss)
            # When aggregation in global model (first) and aggregation with similarities and weights (second), the historical model keeps inmutable
            logging.info("Saving historical model...")
            self.model.save_historical_model()
        except Exception as e:
            logging.exception(f"Error training model: {e}")
            logging.exception(traceback.format_exc())

    def test(self):
        try:
            self.create_trainer()
            self.__trainer.test(self.model, self.data, verbose=True)
        except Exception as e:
            logging.exception(f"Error testing model: {e}")
            logging.exception(traceback.format_exc())

    def get_model_weight(self):
        return (
            len(self.data.train_dataloader().dataset),
            len(self.data.test_dataloader().dataset),
        )

    def finalize_round(self):
        self.logger.global_step = self.logger.global_step + self.logger.local_step
        self.logger.local_step = 0
        self.round += 1
        self.logger.log_data({"Round": self.round}, step=self.logger.global_step)
        pass
