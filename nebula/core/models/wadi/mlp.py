import torch

from nebula.core.models.nebulamodel import NebulaModel


class WADIModelMLP(NebulaModel):
    def __init__(
        self,
        input_channels=1,
        num_classes=10,
        learning_rate=1e-3,
        metrics=None,
        confusion_matrix=None,
        seed=None,
    ):
        super().__init__(input_channels, num_classes, learning_rate, metrics, confusion_matrix, seed)

        self.config = {"beta1": 0.851436, "beta2": 0.999689, "amsgrad": True}

        self.example_input_array = torch.zeros(1, 123)
        self.learning_rate = learning_rate

        self.criterion = torch.nn.BCELoss()

        self.l1 = torch.nn.Linear(123, 1024)
        self.l2 = torch.nn.Linear(1024, 512)
        self.l3 = torch.nn.Linear(512, 256)
        self.l4 = torch.nn.Linear(256, 128)
        self.l5 = torch.nn.Linear(128, 64)
        self.l6 = torch.nn.Linear(64, 32)
        self.l7 = torch.nn.Linear(32, 16)
        self.l8 = torch.nn.Linear(16, 8)
        self.l9 = torch.nn.Linear(8, num_classes)

        self.epoch_global_number = {"Train": 0, "Validation": 0, "Test": 0}

    def forward(self, x):
        batch_size, features = x.size()
        x = self.l1(x)
        x = torch.relu(x)
        x = self.l2(x)
        x = torch.relu(x)
        x = self.l3(x)
        x = torch.relu(x)
        x = self.l4(x)
        x = torch.relu(x)
        x = self.l5(x)
        x = torch.relu(x)
        x = self.l6(x)
        x = torch.relu(x)
        x = self.l7(x)
        x = torch.relu(x)
        x = self.l8(x)
        x = torch.relu(x)
        x = self.l9(x)
        x = torch.sigmoid(x)
        return x

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(self.parameters(), lr=self.learning_rate)
        return optimizer
