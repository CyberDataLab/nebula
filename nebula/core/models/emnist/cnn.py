import torch

from nebula.core.models.nebulamodel import NebulaModel


class EMNISTModelCNN(NebulaModel):
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

        self.example_input_array = torch.rand(1, 1, 28, 28)
        self.learning_rate = learning_rate
        self.criterion = torch.nn.CrossEntropyLoss()

        self.conv1 = torch.nn.Conv2d(
            in_channels=input_channels,
            out_channels=32,
            kernel_size=(5, 5),
            padding="same",
        )
        self.relu = torch.nn.ReLU()
        self.pool1 = torch.nn.MaxPool2d(kernel_size=(2, 2), stride=2)
        self.conv2 = torch.nn.Conv2d(in_channels=32, out_channels=64, kernel_size=(5, 5), padding="same")
        self.pool2 = torch.nn.MaxPool2d(kernel_size=(2, 2), stride=2)
        self.l1 = torch.nn.Linear(7 * 7 * 64, 2048)
        self.l2 = torch.nn.Linear(2048, num_classes)

        self.epoch_global_number = {"Train": 0, "Validation": 0, "Test": 0}

    def forward(self, x):
        input_layer = x.view(-1, 1, 28, 28)
        conv1 = self.relu(self.conv1(input_layer))
        pool1 = self.pool1(conv1)
        conv2 = self.relu(self.conv2(pool1))
        pool2 = self.pool2(conv2)
        pool2_flat = pool2.reshape(-1, 7 * 7 * 64)

        dense = self.relu(self.l1(pool2_flat))
        logits = self.l2(dense)
        return logits

    def configure_optimizers(self):
        optimizer = torch.optim.Adam(
            self.parameters(),
            lr=self.learning_rate,
            betas=(self.config["beta1"], self.config["beta2"]),
            amsgrad=self.config["amsgrad"],
        )
        return optimizer
