import math

import torch

from nebula.core.models.nebulamodel import NebulaModel


class Sentiment140ModelCNN(NebulaModel):
    def __init__(
        self,
        input_channels=3,
        num_classes=10,
        learning_rate=1e-3,
        metrics=None,
        confusion_matrix=None,
        seed=None,
    ):
        super().__init__(input_channels, num_classes, learning_rate, metrics, confusion_matrix, seed)

        self.config = {"beta1": 0.851436, "beta2": 0.999689, "amsgrad": True}
        self.example_input_array = torch.zeros(1, 1, 28, 28)
        self.learning_rate = learning_rate

        self.criterion = torch.nn.CrossEntropyLoss()

        self.filter_sizes = [2, 3, 4]
        self.n_filters = math.ceil(300 * len(self.filter_sizes) / 3)
        self.convs = torch.nn.ModuleList([
            torch.nn.Conv2d(in_channels=1, out_channels=self.n_filters, kernel_size=(fs, 300))
            for fs in self.filter_sizes
        ])
        self.fc = torch.nn.Linear(len(self.filter_sizes) * self.n_filters, self.num_classes)
        self.dropout = torch.nn.Dropout(0.5)

        self.epoch_global_number = {"Train": 0, "Validation": 0, "Test": 0}

    def forward(self, x):
        x = x.unsqueeze(1)
        conved = [
            torch.nn.functional.relu(conv(x)).squeeze(3) for conv in self.convs
        ]  # [(batch_size, n_filters, sent_len), ...] * len(filter_sizes)
        pooled = [
            torch.nn.functional.max_pool1d(conv, conv.shape[2]).squeeze(2) for conv in conved
        ]  # [(batch_size, n_filters), ...] * len(filter_sizes)
        cat = self.dropout(torch.cat(pooled, dim=1))
        out = self.fc(cat)
        return out

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(
            self.parameters(),
            lr=self.learning_rate,
            betas=(self.config["beta1"], self.config["beta2"]),
            amsgrad=self.config["amsgrad"],
        )
        return optimizer
