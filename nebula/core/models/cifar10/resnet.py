import matplotlib
import matplotlib.pyplot as plt
from torch import nn
from torchmetrics import MetricCollection

from nebula.core.models.nebulamodel import NebulaModel

matplotlib.use("Agg")
plt.switch_backend("Agg")
import torch
from torchmetrics.classification import (
    MulticlassAccuracy,
    MulticlassConfusionMatrix,
    MulticlassF1Score,
    MulticlassPrecision,
    MulticlassRecall,
)
from torchvision.models import resnet18, resnet34, resnet50

IMAGE_SIZE = 32

BATCH_SIZE = 256 if torch.cuda.is_available() else 64

classifiers = {
    "resnet18": resnet18(),
    "resnet34": resnet34(),
    "resnet50": resnet50(),
}


class CIFAR10ModelResNet(NebulaModel):
    def __init__(
        self,
        input_channels=3,
        num_classes=10,
        learning_rate=1e-3,
        metrics=None,
        confusion_matrix=None,
        seed=None,
        implementation="scratch",
        classifier="resnet9",
    ):
        super().__init__()
        if metrics is None:
            metrics = MetricCollection([
                MulticlassAccuracy(num_classes=num_classes),
                MulticlassPrecision(num_classes=num_classes),
                MulticlassRecall(num_classes=num_classes),
                MulticlassF1Score(num_classes=num_classes),
            ])
        self.train_metrics = metrics.clone(prefix="Train/")
        self.val_metrics = metrics.clone(prefix="Validation/")
        self.test_metrics = metrics.clone(prefix="Test/")

        if confusion_matrix is None:
            self.cm = MulticlassConfusionMatrix(num_classes=num_classes)
        if seed is not None:
            torch.manual_seed(seed)
            torch.cuda.manual_seed_all(seed)

        self.implementation = implementation
        self.classifier = classifier

        self.example_input_array = torch.rand(1, 3, 32, 32)
        self.learning_rate = learning_rate

        self.criterion = torch.nn.CrossEntropyLoss()

        self.model = self._build_model(input_channels, num_classes)

        self.epoch_global_number = {"Train": 0, "Validation": 0, "Test": 0}

    def _build_model(self, input_channels, num_classes):
        if self.implementation == "scratch":
            if self.classifier == "resnet9":
                """
                ResNet9 implementation
                """

                def conv_block(input_channels, num_classes, pool=False):
                    layers = [
                        nn.Conv2d(input_channels, num_classes, kernel_size=3, padding=1),
                        nn.BatchNorm2d(num_classes),
                        nn.ReLU(inplace=True),
                    ]
                    if pool:
                        layers.append(nn.MaxPool2d(2))
                    return nn.Sequential(*layers)

                conv1 = conv_block(input_channels, 64)
                conv2 = conv_block(64, 128, pool=True)
                res1 = nn.Sequential(conv_block(128, 128), conv_block(128, 128))

                conv3 = conv_block(128, 256, pool=True)
                conv4 = conv_block(256, 512, pool=True)
                res2 = nn.Sequential(conv_block(512, 512), conv_block(512, 512))

                classifier = nn.Sequential(nn.MaxPool2d(4), nn.Flatten(), nn.Linear(512, num_classes))

                return nn.ModuleDict({
                    "conv1": conv1,
                    "conv2": conv2,
                    "res1": res1,
                    "conv3": conv3,
                    "conv4": conv4,
                    "res2": res2,
                    "classifier": classifier,
                })

            if self.implementation in classifiers:
                model = classifiers[self.classifier]
                model.fc = torch.nn.Linear(model.fc.in_features, 10)
                return model

            raise NotImplementedError()

        if self.implementation == "timm":
            raise NotImplementedError()

        raise NotImplementedError()

    def forward(self, x):
        if not isinstance(x, torch.Tensor):
            raise TypeError(f"images must be a torch.Tensor, got {type(x)}")

        if self.implementation == "scratch":
            if self.classifier == "resnet9":
                out = self.model["conv1"](x)
                out = self.model["conv2"](out)
                out = self.model["res1"](out) + out
                out = self.model["conv3"](out)
                out = self.model["conv4"](out)
                out = self.model["res2"](out) + out
                out = self.model["classifier"](out)
                return out

            return self.model(x)
        if self.implementation == "timm":
            raise NotImplementedError()

        raise NotImplementedError()

    def configure_optimizers(self):
        if self.implementation == "scratch" and self.classifier == "resnet9":
            params = []
            for key, module in self.model.items():
                params += list(module.parameters())
            optimizer = torch.optim.Adam(params, lr=self.learning_rate, weight_decay=1e-4)
        else:
            optimizer = torch.optim.Adam(self.parameters(), lr=self.learning_rate, weight_decay=1e-4)
        return optimizer
