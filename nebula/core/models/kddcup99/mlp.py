import torch

from nebula.core.models.nebulamodel import NebulaModel


class KDDCUP99ModelMLP(NebulaModel):
    def __init__(
        self,
        input_channels=1,
        num_classes=2,
        learning_rate=1e-3,
        metrics=None,
        confusion_matrix=None,
        seed=None,
        input_size=118,
        data_type="Tabular",
    ):
        super().__init__(input_channels, num_classes, learning_rate, metrics, confusion_matrix, seed)
        self.data_type = data_type

        self.input_size = input_size
        self.example_input_array = torch.zeros(1, self.input_size)
        self.learning_rate = learning_rate
        self.criterion = torch.nn.CrossEntropyLoss()

        self.l1 = torch.nn.Linear(self.input_size, 256)
        self.l2 = torch.nn.Linear(256, 128)
        self.l3 = torch.nn.Linear(128, num_classes)

    def forward(self, x):
        if x.dim() == 1:
            x = x.unsqueeze(0)

        x = x.view(x.size(0), -1)
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
        self._optimizer = optimizer
        return optimizer

    def get_learning_rate(self):
        return self.learning_rate

    def count_parameters(self):
        return sum(p.numel() for p in self.parameters() if p.requires_grad)

    def get_num_classes(self):
        return self.num_classes

    def get_data_type(self):
        return self.data_type
