# nebula/core/models/covtype/mlp.py

import torch

from nebula.core.models.nebulamodel import NebulaModel


class BreastCancerModelMLP(NebulaModel):
    def __init__(
        self,
        input_dim=30,
        num_classes=2,
        learning_rate=1e-3,
        metrics=None,
        confusion_matrix=None,
        seed=None,
        data_type="Tabular",
    ):
        super().__init__(input_dim, num_classes, learning_rate, metrics, confusion_matrix, seed)
        self.data_type = data_type

        self.config = {"beta1": 0.9, "beta2": 0.999, "amsgrad": True}

        self.example_input_array = torch.rand(1, input_dim)
        self.learning_rate = learning_rate
        self.criterion = torch.nn.CrossEntropyLoss()

        self.l1 = torch.nn.Linear(input_dim, 256)
        self.l2 = torch.nn.Linear(256, 128)
        self.l3 = torch.nn.Linear(128, num_classes)

    def forward(self, x):
        if x.dim() == 3 and x.size(1) == 1:
            x = x.squeeze(1)

        x = self.l1(x)
        x = torch.relu(x)
        x = self.l2(x)
        x = torch.relu(x)
        x = self.l3(x)
        return x

    def configure_optimizers(self):
        optimizer_override = self.get_optimizer_override()
        if optimizer_override is not None:
            return optimizer_override

        optimizer = torch.optim.Adam(self.parameters(), lr=self.learning_rate)
        return optimizer

    def get_learning_rate(self) -> float:
        return float(self.learning_rate)

    def count_parameters(self) -> int:
        return int(sum(p.numel() for p in self.parameters() if p.requires_grad))

    def get_num_classes(self):
        return self.num_classes

    def get_data_type(self):
        return self.data_type
