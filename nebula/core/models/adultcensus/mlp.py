# nebula/core/models/adultcensus/mlp.py

import torch

from nebula.core.models.nebulamodel import NebulaModel


class AdultCensusModelMLP(NebulaModel):
    """
    Simple MLP for Adult Census (tabular).
    - input_dim MUST match the number of features after preprocessing (OneHot + scaling).
    - num_classes = 2 (<=50K vs >50K)
    """
    def __init__(
        self,
        input_dim: int = 104,
        num_classes: int = 2,
        learning_rate: float = 1e-3,
        metrics=None,
        confusion_matrix=None,
        seed=None,
        hidden1: int = 256,
        hidden2: int = 128,
        dropout: float = 0.0,
        data_type="Tabular",
    ):
        # NebulaModel expects something like input_channels first; for tabular we pass input_dim there.
        super().__init__(input_dim, num_classes, learning_rate, metrics, confusion_matrix, seed)
        self.data_type = data_type

        self.config = {"beta1": 0.9, "beta2": 0.999, "amsgrad": True}

        self.example_input_array = torch.rand(1, int(input_dim))
        self.learning_rate = float(learning_rate)
        self.criterion = torch.nn.CrossEntropyLoss()

        self.l1 = torch.nn.Linear(int(input_dim), int(hidden1))
        self.l2 = torch.nn.Linear(int(hidden1), int(hidden2))
        self.l3 = torch.nn.Linear(int(hidden2), int(num_classes))

        self.dropout = torch.nn.Dropout(float(dropout)) if float(dropout) > 0.0 else None

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Expected: (batch, input_dim). Sometimes: (batch, 1, input_dim)
        if x.dim() == 3 and x.size(1) == 1:
            x = x.squeeze(1)

        x = self.l1(x)
        x = torch.relu(x)
        if self.dropout is not None:
            x = self.dropout(x)

        x = self.l2(x)
        x = torch.relu(x)
        if self.dropout is not None:
            x = self.dropout(x)

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
