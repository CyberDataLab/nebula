import torch
import torchmetrics

from nebula.core.models.nebulamodel import NebulaModel


class SyscallModelSGDOneClassSVM(NebulaModel):
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
        self.nu = 0.1

        self.w = torch.nn.Parameter(torch.zeros(input_channels), requires_grad=True)
        self.rho = torch.nn.Parameter(torch.zeros(1), requires_grad=True)

        self.epoch_global_number = {"Train": 0, "Validation": 0, "Test": 0}

    def forward(self, x):
        return torch.matmul(x, self.w) - self.rho

    def configure_optimizers(self):
        optimizer = torch.optim.SGD(self.parameters(), lr=self.learning_rate)
        return optimizer

    def hinge_loss(self, y):
        return torch.mean(torch.clamp(1 - y, min=0))

    def step(self, batch, batch_idx, phase):
        x, labels = batch
        x = x.to(self.device)
        labels = labels.to(self.device)
        y_pred = self.forward(x)
        if phase == "Train":
            loss = 0.5 * torch.sum(self.w**2) + self.nu * self.hinge_loss(y_pred)
            self.log(f"{phase}/Loss", loss, prog_bar=True)
        else:
            y_pred_classes = (y_pred > 0).type(torch.int64)
            loss = torch.nn.functional.binary_cross_entropy_with_logits(y_pred, labels.float())
            self.log(f"{phase}/Loss", loss, prog_bar=True)
            self.log(
                f"{phase}/Accuracy",
                torchmetrics.functional.accuracy(y_pred_classes, labels, task="multiclass"),
                prog_bar=True,
            )
        return loss
