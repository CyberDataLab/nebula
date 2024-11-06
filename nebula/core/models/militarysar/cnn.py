import torch

from nebula.core.models.militarysar import _blocks
from nebula.core.models.nebulamodel import NebulaModel


class MilitarySARModelCNN(NebulaModel):
    def __init__(
        self,
        input_channels=2,
        num_classes=10,
        learning_rate=1e-3,
        metrics=None,
        confusion_matrix=None,
        seed=None,
    ):
        super().__init__(input_channels, num_classes, learning_rate, metrics, confusion_matrix, seed)

        self.example_input_array = torch.zeros((1, input_channels, 128, 128))
        self.learning_rate = learning_rate
        self.momentum = 0.9
        self.weight_decay = 4e-3
        self.dropout_rate = 0.5
        self.criterion = torch.nn.CrossEntropyLoss()

        self.model = torch.nn.Sequential(
            _blocks.Conv2DBlock(
                shape=[5, 5, self.input_channels, 16],
                stride=1,
                padding="valid",
                activation="relu",
                max_pool=True,
            ),
            _blocks.Conv2DBlock(
                shape=[5, 5, 16, 32],
                stride=1,
                padding="valid",
                activation="relu",
                max_pool=True,
            ),
            _blocks.Conv2DBlock(
                shape=[6, 6, 32, 64],
                stride=1,
                padding="valid",
                activation="relu",
                max_pool=True,
            ),
            _blocks.Conv2DBlock(shape=[5, 5, 64, 128], stride=1, padding="valid", activation="relu"),
            torch.nn.Dropout(p=self.dropout_rate),
            _blocks.Conv2DBlock(shape=[3, 3, 128, self.num_classes], stride=1, padding="valid"),
            torch.nn.Flatten(),
            torch.nn.Linear(360, num_classes),
        )

    def forward(self, x):
        logits = self.model(x)
        return logits

    def configure_optimizers(self):
        optimizer = torch.optim.SGD(
            self.parameters(),
            lr=self.learning_rate,
            momentum=self.momentum,
            weight_decay=self.weight_decay,
        )
        # optimizer = torch.optim.Adam(
        #     self.parameters(),
        #     lr=self.learning_rate,
        #     weight_decay=self.weight_decay
        # )
        lr_scheduler = torch.optim.lr_scheduler.StepLR(optimizer=optimizer, step_size=50, gamma=0.1)
        # optimizer = torch.optim.Adam(
        #     self.parameters(),
        #     lr=self.learning_rate
        # )
        # lr_scheduler = torch.optim.lr_scheduler.MultiStepLR(
        #     optimizer=optimizer,
        #     milestones=self.lr_step,
        #     gamma=self.lr_decay
        # )
        return [optimizer], [lr_scheduler]
