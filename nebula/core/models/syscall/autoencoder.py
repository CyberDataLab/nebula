import torch

from nebula.core.models.nebulamodel import NebulaModel


class SyscallModelAutoencoder(NebulaModel):
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

        self.example_input_array = torch.rand(1, input_channels)
        self.learning_rate = learning_rate

        self.criterion = torch.nn.MSELoss()

        self.fc1 = torch.nn.Linear(input_channels, 64)
        self.fc2 = torch.nn.Linear(64, 16)
        self.fc3 = torch.nn.Linear(16, 8)
        self.fc4 = torch.nn.Linear(8, 16)
        self.fc5 = torch.nn.Linear(16, 64)
        self.fc6 = torch.nn.Linear(64, input_channels)

        self.epoch_global_number = {"Train": 0, "Validation": 0, "Test": 0}

    def encode(self, x):
        z = torch.relu(self.fc1(x))
        z = torch.relu(self.fc2(z))
        z = torch.relu(self.fc3(z))
        return z

    def decode(self, x):
        z = torch.relu(self.fc4(x))
        z = torch.relu(self.fc5(z))
        z = torch.relu(self.fc6(z))
        return z

    def forward(self, x):
        z = self.encode(x)
        z = self.decode(z)
        return z

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(self.parameters(), lr=self.learning_rate)
        return optimizer
