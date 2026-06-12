from abc import ABC, abstractmethod

import torch


class AdversarialExampleGenerator(ABC):
    """Base interface for domain-specific adversarial example generators."""

    last_epsilon: float | None = None

    @abstractmethod
    def generate(self, model, x, y, criterion):
        # Concrete generators must return an adversarial version of the input batch.
        raise NotImplementedError

    def _sample_epsilon(self, device: torch.device) -> float:
        # Sample the effective epsilon on the same device as the batch.
        epsilon_max = float(self.config.epsilon)
        if epsilon_max <= 0.0:
            self.last_epsilon = 0.0
            return 0.0

        # Use a different attack strength per batch, capped by the user epsilon.
        epsilon_min = epsilon_max / 4.0
        epsilon_step = epsilon_max / 8.0
        num_values = max(round((epsilon_max - epsilon_min) / epsilon_step) + 1, 1)
        index = int(torch.randint(num_values, (), device=device).item())
        epsilon = min(epsilon_min + index * epsilon_step, epsilon_max)
        self.last_epsilon = epsilon
        return epsilon
