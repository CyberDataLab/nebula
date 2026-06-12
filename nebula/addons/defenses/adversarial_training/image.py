import torch

from nebula.addons.defenses.adversarial_training.base import AdversarialExampleGenerator
from nebula.addons.defenses.adversarial_training.config import AdversarialTrainingConfig

IMAGE_CLIP_MIN = 0.0
IMAGE_CLIP_MAX = 1.0


class ImageAdversarialExampleGenerator(AdversarialExampleGenerator):
    def __init__(self, config: AdversarialTrainingConfig, mean: tuple[float, ...], std: tuple[float, ...]):
        # Store normalization values so attacks can move between pixel and model space.
        self.config = config
        self.mean = mean
        self.std = std

    def _channel_tensor(self, values: tuple[float, ...], x: torch.Tensor) -> torch.Tensor:
        # Reshape per-channel values so they broadcast over the whole image batch.
        shape = [1, len(values)] + [1] * max(x.dim() - 2, 0)
        return torch.tensor(values, dtype=x.dtype, device=x.device).view(*shape)

    def _epsilon(self, x: torch.Tensor, epsilon: float) -> torch.Tensor:
        # Image batches are normalized, so pixel-space epsilon must be scaled by std.
        std = self._channel_tensor(self.std, x)
        return float(epsilon) / std

    def _alpha(self, x: torch.Tensor, epsilon: float) -> torch.Tensor:
        # Use the configured step size, or split epsilon across PGD steps by default.
        alpha = self.config.alpha
        if alpha is None:
            alpha = epsilon / max(int(self.config.steps), 1)
        std = self._channel_tensor(self.std, x)
        return float(alpha) / std

    def _bounds(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        # Convert valid pixel bounds to the normalized space where the model operates.
        mean = self._channel_tensor(self.mean, x)
        std = self._channel_tensor(self.std, x)
        lower = (IMAGE_CLIP_MIN - mean) / std
        upper = (IMAGE_CLIP_MAX - mean) / std
        return lower, upper

    def denormalize(self, x: torch.Tensor) -> torch.Tensor:
        # Convert normalized tensors back to pixel scale for logging.
        mean = self._channel_tensor(self.mean, x)
        std = self._channel_tensor(self.std, x)
        return (x * std + mean).clamp(IMAGE_CLIP_MIN, IMAGE_CLIP_MAX)

    def _project(self, x_adv: torch.Tensor, x_clean: torch.Tensor, epsilon: float) -> torch.Tensor:
        # Keep the adversarial image inside both the epsilon ball and valid pixel bounds.
        epsilon = self._epsilon(x_clean, epsilon)
        lower, upper = self._bounds(x_clean)
        x_adv = torch.max(torch.min(x_adv, x_clean + epsilon), x_clean - epsilon)
        return torch.max(torch.min(x_adv, upper), lower)


class ImageFGSMGenerator(ImageAdversarialExampleGenerator):
    def generate(self, model, x, y, criterion):
        # Build one adversarial image batch with a single gradient step.
        epsilon = self._sample_epsilon(x.device)
        x_adv = x.detach().clone().requires_grad_(True)
        logits = model(x_adv)
        loss = criterion(logits, y)
        grad = torch.autograd.grad(loss, x_adv, only_inputs=True)[0]
        # FGSM takes one step in the sign of the loss gradient.
        x_adv = x_adv + self._epsilon(x_adv, epsilon) * grad.sign()
        return self._project(x_adv.detach(), x.detach(), epsilon)


class ImagePGDGenerator(ImageAdversarialExampleGenerator):
    def generate(self, model, x, y, criterion):
        # Build one adversarial image batch with iterative projected gradient steps.
        epsilon = self._sample_epsilon(x.device)
        x_clean = x.detach()
        x_adv = x_clean.clone()
        steps = max(int(self.config.steps), 1)

        for _ in range(steps):
            x_adv = x_adv.detach().requires_grad_(True)
            logits = model(x_adv)
            loss = criterion(logits, y)
            grad = torch.autograd.grad(loss, x_adv, only_inputs=True)[0]
            # PGD repeats smaller FGSM-like steps and projects after each step.
            x_adv = x_adv + self._alpha(x_adv, epsilon) * grad.sign()
            x_adv = self._project(x_adv.detach(), x_clean, epsilon)

        return x_adv.detach()
