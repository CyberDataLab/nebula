import torch
from torch import nn

from nebula.core.models.nebulamodel import NebulaModel


class FasterMobileNet(NebulaModel):
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

        self.example_input_array = torch.rand(1, 3, 32, 32)
        self.learning_rate = learning_rate
        self.criterion = torch.torch.nn.CrossEntropyLoss()

        def conv_dw(input_channels, num_classes, stride):
            return nn.Sequential(
                nn.Conv2d(
                    input_channels,
                    input_channels,
                    3,
                    stride,
                    1,
                    groups=input_channels,
                    bias=False,
                ),
                nn.BatchNorm2d(input_channels),
                nn.ReLU(inplace=True),
                nn.Conv2d(input_channels, num_classes, 1, 1, 0, bias=False),
                nn.BatchNorm2d(num_classes),
                nn.ReLU(inplace=True),
            )

        self.model = nn.Sequential(
            nn.Conv2d(3, 16, 3, 1, 1, bias=False),
            nn.BatchNorm2d(16),
            nn.ReLU(inplace=True),
            conv_dw(16, 32, 1),
            conv_dw(32, 64, 2),
            conv_dw(64, 64, 1),
            nn.AdaptiveAvgPool2d(1),
        )
        self.fc = nn.Linear(64, num_classes)

    def forward(self, x):
        x = self.model(x)
        x = x.view(-1, 64)
        x = self.fc(x)
        return x

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(
            self.parameters(),
            lr=self.learning_rate,
            betas=(self.config["beta1"], self.config["beta2"]),
            amsgrad=self.config["amsgrad"],
        )
        return optimizer
