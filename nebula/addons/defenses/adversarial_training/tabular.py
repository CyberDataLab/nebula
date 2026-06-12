import torch
import torch.nn.functional as F

from nebula.addons.defenses.adversarial_training.base import AdversarialExampleGenerator
from nebula.addons.defenses.adversarial_training.config import AdversarialTrainingConfig
from nebula.core.datasets.tabular_metadata import CATEGORICAL, CONTINUOUS, INTEGER, TabularAdversarialMetadata


class TabularConstraintSet:
    """Projects tabular attack candidates back to the valid feature domain."""

    def __init__(self, metadata: TabularAdversarialMetadata):
        # The metadata is dataset-level and immutable; derived tensors are cached per device/dtype.
        self.metadata = metadata
        self._tensor_cache: dict[tuple[torch.device, torch.dtype], dict[str, torch.Tensor]] = {}

    def tensors(self, x: torch.Tensor) -> dict[str, torch.Tensor]:
        # Masks and bounds are reused in every constrained PGD step, so build them once per placement.
        key = (x.device, x.dtype)
        cached = self._tensor_cache.get(key)
        if cached is not None:
            return cached

        # Masks have shape (1, n_features), which broadcasts over the batch dimension.
        cached = {
            "continuous": self._feature_type_mask(x, CONTINUOUS),
            "integer": self._feature_type_mask(x, INTEGER),
            "categorical": self._feature_type_mask(x, CATEGORICAL),
            "min": torch.tensor(self.metadata.feature_min_norm, dtype=x.dtype, device=x.device).view(1, -1),
            "max": torch.tensor(self.metadata.feature_max_norm, dtype=x.dtype, device=x.device).view(1, -1),
        }
        cached["numeric"] = cached["continuous"] | cached["integer"]
        cached["perturbable"] = cached["numeric"] | cached["categorical"]
        cached["integer_step"] = self._integer_steps(cached["min"])
        self._tensor_cache[key] = cached
        return cached

    def perturbable_mask(self, x: torch.Tensor) -> torch.Tensor:
        # Used by the attack step to avoid moving immutable features in the first place.
        return self.tensors(x)["perturbable"]

    def project(self, x_candidate: torch.Tensor, x_clean: torch.Tensor, epsilon: float) -> torch.Tensor:
        # Clamp numeric features, round integers, restore immutable features and fix one-hot groups.
        tensors = self.tensors(x_clean)
        lower, upper = self._bounds(x_clean, epsilon, tensors)

        # First force every value into its valid interval, then apply type-specific fixes.
        x_projected = torch.max(torch.min(x_candidate, upper), lower)
        x_projected = self._project_integer_features(x_projected, x_clean, lower, upper, tensors)
        x_projected = self.project_categorical_groups(x_projected)
        # Immutable features are copied back from the original clean sample as the final guardrail.
        return torch.where(tensors["perturbable"], x_projected, x_clean)

    def categorical_gradient_step(self, x_candidate: torch.Tensor, grad: torch.Tensor) -> torch.Tensor:
        if not self.metadata.categorical_groups:
            return x_candidate

        # One-hot columns are discrete: instead of adding a fractional gradient,
        # activate the category whose gradient most increases the adversarial loss.
        x_stepped = x_candidate.clone()
        for group in self.metadata.categorical_groups:
            group_tensor = torch.tensor(group, dtype=torch.long, device=x_candidate.device)
            selected = grad.index_select(1, group_tensor).argmax(dim=1)
            x_stepped[:, group_tensor] = F.one_hot(selected, num_classes=len(group)).to(dtype=x_candidate.dtype)
        return x_stepped

    def project_categorical_groups(self, x_candidate: torch.Tensor) -> torch.Tensor:
        if not self.metadata.categorical_groups:
            return x_candidate

        # Projection must always leave each one-hot group with exactly one active feature.
        x_projected = x_candidate.clone()
        for group in self.metadata.categorical_groups:
            group_tensor = torch.tensor(group, dtype=torch.long, device=x_candidate.device)
            selected = x_candidate.index_select(1, group_tensor).argmax(dim=1)
            x_projected[:, group_tensor] = F.one_hot(selected, num_classes=len(group)).to(dtype=x_candidate.dtype)
        return x_projected

    def _feature_type_mask(self, x: torch.Tensor, feature_type: str) -> torch.Tensor:
        return torch.tensor(
            [value == feature_type for value in self.metadata.feature_types],
            dtype=torch.bool,
            device=x.device,
        ).view(1, -1)

    def _bounds(
        self,
        x_clean: torch.Tensor,
        epsilon: float,
        tensors: dict[str, torch.Tensor],
    ) -> tuple[torch.Tensor, torch.Tensor]:
        # Numeric features are restricted both by dataset bounds and by the epsilon ball around x_clean.
        numeric_lower = torch.maximum(tensors["min"], x_clean - float(epsilon))
        numeric_upper = torch.minimum(tensors["max"], x_clean + float(epsilon))
        # Categorical features are handled by one-hot projection, not by an epsilon ball.
        lower = torch.where(tensors["categorical"], tensors["min"], numeric_lower)
        upper = torch.where(tensors["categorical"], tensors["max"], numeric_upper)
        return lower, upper

    def _integer_steps(self, minimum: torch.Tensor) -> torch.Tensor:
        # Default step=1 is harmless for non-integer columns because the integer mask gates usage later.
        integer_steps = torch.ones_like(minimum)
        for idx, step in (self.metadata.integer_step_norm or {}).items():
            integer_steps[0, int(idx)] = float(step)
        return integer_steps

    def _project_integer_features(
        self,
        x_projected: torch.Tensor,
        x_clean: torch.Tensor,
        lower: torch.Tensor,
        upper: torch.Tensor,
        tensors: dict[str, torch.Tensor],
    ) -> torch.Tensor:
        integer_mask = tensors["integer"]
        if not integer_mask.any():
            return x_projected

        # Integer features may be normalized, so the valid values form a shifted grid:
        # min, min + step, min + 2*step, ...
        step = torch.clamp(tensors["integer_step"], min=torch.finfo(x_projected.dtype).eps)
        grid_lower = torch.ceil((lower - tensors["min"]) / step) * step + tensors["min"]
        grid_upper = torch.floor((upper - tensors["min"]) / step) * step + tensors["min"]
        rounded = torch.round((x_projected - tensors["min"]) / step) * step + tensors["min"]
        rounded = torch.max(torch.min(rounded, grid_upper), grid_lower)

        # If epsilon is smaller than the normalized integer step, no valid integer move exists.
        has_valid_grid = grid_lower <= grid_upper
        rounded = torch.where(has_valid_grid, rounded, x_clean)
        return torch.where(integer_mask, rounded, x_projected)


class TabularAdversarialExampleGenerator(AdversarialExampleGenerator):
    """Base generator for constrained tabular adversarial examples."""

    def __init__(self, config: AdversarialTrainingConfig, metadata: TabularAdversarialMetadata):
        # Generators share the same constraint layer; only the search strategy should vary.
        self.config = config
        self.metadata = metadata
        self.constraints = TabularConstraintSet(metadata)

    def _alpha(self, epsilon: float) -> float:
        # By default, distribute the epsilon budget evenly across constrained PGD steps.
        if self.config.alpha is not None:
            return float(self.config.alpha)
        return float(epsilon) / max(int(self.config.steps), 1)

    def _margin(self, logits: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
        # Positive margin means some wrong class already beats the true class.
        true_logits = logits.gather(1, y.view(-1, 1)).squeeze(1)
        true_class_mask = F.one_hot(y, num_classes=logits.size(1)).bool()
        other_logits = logits.masked_fill(true_class_mask, float("-inf"))
        return other_logits.max(dim=1).values - true_logits

    def _per_sample_loss(self, logits: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
        # The attack needs per-sample scores so each row can stop once it is hard enough.
        return F.cross_entropy(logits, y, reduction="none")


class TabularConstrainedPGDGenerator(TabularAdversarialExampleGenerator):
    """Constrained PGD generator for tabular adversarial examples."""

    def generate(self, model, x, y, criterion):
        # Sample one attack strength for this batch, matching the image generator behavior.
        epsilon = self._sample_epsilon(x.device)
        x_clean = x.detach()
        if epsilon <= 0.0:
            return x_clean

        steps = max(int(self.config.steps), 1)
        step_size = self._alpha(epsilon)
        perturbable_mask = self.constraints.perturbable_mask(x_clean).to(dtype=x_clean.dtype)

        x_adv = x_clean.clone()
        best_adv = x_adv.clone()
        best_score = torch.full((x_clean.size(0),), float("-inf"), dtype=x_clean.dtype, device=x_clean.device)
        best_distance = torch.full((x_clean.size(0),), float("inf"), dtype=x_clean.dtype, device=x_clean.device)
        use_loss_window = self._use_loss_window()
        use_margin_window = self._use_margin_window()
        clean_loss = self._clean_loss(model, x_clean, y) if use_loss_window else None

        for _ in range(steps):
            # PGD step: move in the sign of the loss gradient, but only on perturbable features.
            x_grad = x_adv.detach().requires_grad_(True)
            logits = model(x_grad)
            loss = criterion(logits, y)
            grad = torch.autograd.grad(loss, x_grad, only_inputs=True)[0]

            candidate = x_adv.detach() + float(step_size) * grad.sign() * perturbable_mask
            candidate = self.constraints.categorical_gradient_step(candidate, grad)
            # This is the key tabular rule: never score or return an invalid candidate.
            candidate = self.constraints.project(candidate, x_clean, epsilon)

            with torch.no_grad():
                # Keep the best candidate per sample, not just the last step.
                candidate_logits = model(candidate)
                if use_loss_window:
                    candidate_score = self._loss_increase(candidate_logits, y, clean_loss)
                    better = self._loss_window_better(candidate_score, best_score)
                elif use_margin_window:
                    candidate_score = self._margin(candidate_logits, y)
                    candidate_distance = self._margin_window_distance(candidate_score)
                    better = self._margin_window_better(candidate_score, candidate_distance, best_score, best_distance)
                    best_distance = torch.where(better, candidate_distance, best_distance)
                else:
                    candidate_score = self._margin(candidate_logits, y)
                    better = candidate_score > best_score
                best_adv = torch.where(better.view(-1, 1), candidate, best_adv)
                best_score = torch.where(better, candidate_score, best_score)

                if self._target_reached(best_score, best_distance):
                    break

            x_adv = candidate

        return best_adv.detach()

    def _use_loss_window(self) -> bool:
        return self.config.candidate_selection == "loss_window"

    def _use_margin_window(self) -> bool:
        return self.config.candidate_selection == "margin_window"

    def _clean_loss(self, model, x_clean: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
        # Baseline difficulty. Candidate scores become loss(candidate) - loss(clean).
        with torch.no_grad():
            return self._per_sample_loss(model(x_clean), y)

    def _loss_increase(
        self,
        candidate_logits: torch.Tensor,
        y: torch.Tensor,
        clean_loss: torch.Tensor,
    ) -> torch.Tensor:
        return self._per_sample_loss(candidate_logits, y) - clean_loss

    def _loss_window_better(self, candidate_score: torch.Tensor, best_score: torch.Tensor) -> torch.Tensor:
        # A candidate must make the sample harder. If max_loss_increase is set, reject overshoots.
        valid = candidate_score > 0.0
        if self.config.max_loss_increase is not None:
            valid = valid & (candidate_score <= float(self.config.max_loss_increase))
        return valid & (candidate_score > best_score)

    def _margin_window_distance(self, margin: torch.Tensor) -> torch.Tensor:
        # Distance is zero inside the window and positive outside. This gives a
        # soft fallback when discrete tabular steps jump over the desired range.
        distance = torch.zeros_like(margin)
        if self.config.target_margin is not None:
            target = torch.full_like(margin, float(self.config.target_margin))
            distance = torch.maximum(distance, target - margin)
        if self.config.max_margin is not None:
            maximum = torch.full_like(margin, float(self.config.max_margin))
            distance = torch.maximum(distance, margin - maximum)
        return distance

    def _margin_window_better(
        self,
        candidate_score: torch.Tensor,
        candidate_distance: torch.Tensor,
        best_score: torch.Tensor,
        best_distance: torch.Tensor,
    ) -> torch.Tensor:
        closer = candidate_distance < best_distance
        same_distance = candidate_distance == best_distance
        stronger = candidate_score > best_score
        return closer | (same_distance & stronger)

    def _target_reached(self, best_score: torch.Tensor, best_distance: torch.Tensor) -> bool:
        if self._use_loss_window():
            if self.config.target_loss_increase is None:
                return False
            return bool((best_score >= float(self.config.target_loss_increase)).all().item())
        if self._use_margin_window():
            return bool((best_distance <= torch.finfo(best_distance.dtype).eps).all().item())
        return False
