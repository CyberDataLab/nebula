import torch

from nebula.core.models.nebulamodel import NebulaModel


class CIFAR100ModelCNN(NebulaModel):
    def __init__(
        self,
        input_channels=3,
        num_classes=100,
        learning_rate=1e-3,
        metrics=None,
        confusion_matrix=None,
        seed=None,
    ):
        super().__init__(input_channels, num_classes, learning_rate, metrics, confusion_matrix, seed)

        self.config = {
            "lr": 8.0505e-05,
            "beta1": 0.851436,
            "beta2": 0.999689,
            "amsgrad": True,
        }

        self.example_input_array = torch.rand(1, 3, 32, 32)

        self.criterion = torch.torch.nn.CrossEntropyLoss()

        self.conv1 = torch.nn.Sequential(
            torch.nn.Conv2d(in_channels=3, out_channels=64, kernel_size=3, padding=1),
            torch.nn.BatchNorm2d(64),
            torch.nn.ReLU(inplace=True),
        )
        self.conv2 = torch.nn.Sequential(
            torch.nn.Conv2d(in_channels=64, out_channels=128, kernel_size=3, padding=1),
            torch.nn.BatchNorm2d(128),
            torch.nn.ReLU(inplace=True),
            torch.nn.MaxPool2d(2),
        )

        self.res1 = torch.nn.Sequential(
            torch.nn.Sequential(
                torch.nn.Conv2d(in_channels=128, out_channels=128, kernel_size=3, padding=1),
                torch.nn.BatchNorm2d(128),
                torch.nn.ReLU(inplace=True),
            ),
            torch.nn.Sequential(
                torch.nn.Conv2d(in_channels=128, out_channels=128, kernel_size=3, padding=1),
                torch.nn.BatchNorm2d(128),
                torch.nn.ReLU(inplace=True),
            ),
        )

        self.conv3 = torch.nn.Sequential(
            torch.nn.Conv2d(in_channels=128, out_channels=256, kernel_size=3, padding=1),
            torch.nn.BatchNorm2d(256),
            torch.nn.ReLU(inplace=True),
            torch.nn.MaxPool2d(2),
        )
        self.conv4 = torch.nn.Sequential(
            torch.nn.Conv2d(in_channels=256, out_channels=512, kernel_size=3, padding=1),
            torch.nn.BatchNorm2d(512),
            torch.nn.ReLU(inplace=True),
            torch.nn.MaxPool2d(2),
        )

        self.res2 = torch.nn.Sequential(
            torch.nn.Sequential(
                torch.nn.Conv2d(in_channels=512, out_channels=512, kernel_size=3, padding=1),
                torch.nn.BatchNorm2d(512),
                torch.nn.ReLU(inplace=True),
            ),
            torch.nn.Sequential(
                torch.nn.Conv2d(in_channels=512, out_channels=512, kernel_size=3, padding=1),
                torch.nn.BatchNorm2d(512),
                torch.nn.ReLU(inplace=True),
            ),
        )

        self.classifier = torch.nn.Sequential(
            torch.nn.MaxPool2d(4),
            torch.nn.Flatten(),
            torch.nn.Linear(512, self.num_classes),
        )

    def forward(self, x):
        x = self.conv1(x)
        x = self.conv2(x)
        x = self.res1(x) + x
        x = self.conv3(x)
        x = self.conv4(x)
        x = self.res2(x) + x
        x = self.classifier(x)
        return x

    def configure_optimizers(self):
        return torch.optim.Adam(
            self.parameters(),
            lr=self.config["lr"],
            betas=(self.config["beta1"], self.config["beta2"]),
            amsgrad=self.config["amsgrad"],
        )
