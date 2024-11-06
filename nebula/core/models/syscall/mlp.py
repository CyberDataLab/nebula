import torch

from nebula.core.models.nebulamodel import NebulaModel


class SyscallModelMLP(NebulaModel):
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

        self.example_input_array = torch.rand(1, 17)
        self.learning_rate = learning_rate

        self.criterion = torch.nn.CrossEntropyLoss()

        self.l1 = torch.nn.Linear(17, 256)
        self.batchnorm1 = torch.nn.BatchNorm1d(256)
        self.dropout = torch.nn.Dropout(0.5)
        self.l2 = torch.nn.Linear(256, 128)
        self.batchnorm2 = torch.nn.BatchNorm1d(128)
        self.l3 = torch.nn.Linear(128, num_classes)

    def forward(self, x):
        x = self.l1(x)
        x = self.batchnorm1(x)
        x = torch.relu(x)
        x = self.dropout(x)
        x = self.l2(x)
        x = self.batchnorm2(x)
        x = torch.relu(x)
        x = self.dropout(x)
        x = self.l3(x)
        return x

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(self.parameters(), lr=self.learning_rate)
        return optimizer
