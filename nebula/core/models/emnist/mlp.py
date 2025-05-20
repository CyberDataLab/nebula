import torch

from nebula.core.models.nebulamodel import NebulaModel


class EMNISTModelMLP(NebulaModel):
    def __init__(
        self,
        input_channels=1,
        num_classes=47,
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

        self.l1 = torch.nn.Linear(28 * 28, 256)
        self.l2 = torch.nn.Linear(256, 128)
        self.l3 = torch.nn.Linear(128, num_classes)

    def forward(self, x):
        batch_size, channels, width, height = x.size()
        x = x.view(batch_size, -1)
        x = self.l1(x)
        x = torch.relu(x)
        x = self.l2(x)
        x = torch.relu(x)
        x = self.l3(x)
        return x

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(self.parameters(), lr=self.learning_rate)
        return optimizer
