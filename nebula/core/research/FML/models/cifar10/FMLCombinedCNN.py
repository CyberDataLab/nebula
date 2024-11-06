import torch

from nebula.core.research.FML.models.cifar10.FMLMemeCNN import FMLCIFAR10MemeModelCNN
from nebula.core.research.FML.models.cifar10.FMLPersonalizedCNN import FMLCIFAR10PersonalizedModelCNN
from nebula.core.research.FML.models.fmlcombinedmodel import FMLCombinedNebulaModel


class FMLCIFAR10CombinedModelCNN(FMLCombinedNebulaModel):
    def __init__(
        self,
        input_channels=3,
        num_classes=10,
        learning_rate=1e-3,
        metrics=None,
        confusion_matrix=None,
        seed=None,
        T=2,
        beta=0.2,  # 2006.16765v3 ("Dynamic alphabeta at different stage of training can improve both global and local performance")
        alpha=0.2,
        model_meme=None,
        model_local=None,
    ):

        super().__init__(input_channels, num_classes, learning_rate, metrics, confusion_matrix, seed, T, beta, alpha, model_meme, model_local)

        if self.model_meme is None:
            self.model_meme = FMLCIFAR10MemeModelCNN(
                input_channels,
                num_classes,
                learning_rate,
                metrics,
                confusion_matrix,
                seed,
                T,
                beta,
            )

        if self.model_local is None:
            self.model_local = FMLCIFAR10PersonalizedModelCNN(
                input_channels,
                num_classes,
                learning_rate,
                metrics,
                confusion_matrix,
                seed,
                T,
                alpha,
            )

        self.example_input_array = torch.rand(1, 3, 32, 32)

    def configure_optimizers(self):
        """Configure the optimizer for training."""
        opt_local = torch.optim.Adam(
            self.model_local.parameters(),
            lr=self.learning_rate,
            betas=(self.config["beta1"], self.config["beta2"]),
            amsgrad=self.config["amsgrad"],
        )

        opt_meme = torch.optim.Adam(
            self.model_meme.parameters(),
            lr=self.learning_rate,
            betas=(self.config["beta1"], self.config["beta2"]),
            amsgrad=self.config["amsgrad"],
        )

        return opt_local, opt_meme
