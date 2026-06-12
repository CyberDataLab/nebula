import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import torch
from PIL import Image

PIL_IMAGE_MODES = {"1", "L", "P", "RGB", "RGBA", "CMYK", "YCbCr"}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeatureSqueezingConfig:
    enabled: bool = False
    bit_depth: int = 8
    dataset_name: str | None = None
    apply_to_train: bool = True
    apply_to_test: bool = True
    apply_to_local_test: bool = True


# ---------------------------------------------------------------------------
# Defense
# ---------------------------------------------------------------------------


class FeatureSqueezingDefense:
    """Dataset-level feature squeezing for image Nebula datasets."""

    def __init__(self, config: FeatureSqueezingConfig):
        # Validate the number of quantization levels requested by the scenario.
        if not isinstance(config.bit_depth, int) or not 1 <= config.bit_depth <= 64:
            raise ValueError("feature_squeezing.bit_depth must be an integer in [1, 64]")

        self.config = config
        self.levels = float((2**config.bit_depth) - 1)

    @classmethod
    def from_participant_config(cls, participant_config: dict[str, Any]) -> "FeatureSqueezingDefense | None":
        # Build the defense only when feature squeezing is enabled in the participant config.
        raw = participant_config.get("defense_args", {}).get("feature_squeezing", {})
        if not raw or not raw.get("enabled", False):
            return None

        return cls(
            FeatureSqueezingConfig(
                enabled=True,
                bit_depth=int(raw.get("bit_depth", raw.get("n", 8))),
                dataset_name=participant_config.get("data_args", {}).get("dataset"),
                apply_to_train=bool(raw.get("apply_to_train", True)),
                apply_to_test=bool(raw.get("apply_to_test", True)),
                apply_to_local_test=bool(raw.get("apply_to_local_test", True)),
            )
        )

    def apply_to_partition(self, partition) -> None:
        # Apply the defense to each enabled split in the participant partition.
        train_set = getattr(partition, "train_set", None)
        if train_set is None:
            logging.warning("[FeatureSqueezingDefense] No train set found; skipping defense")
            return

        logging.info(
            "[FeatureSqueezingDefense] Applying feature squeezing | dataset=%s | bit_depth=%s",
            self.config.dataset_name,
            self.config.bit_depth,
        )

        seen_data: set[int] = set()
        for name, dataset, enabled in (
            ("train", train_set, self.config.apply_to_train),
            ("test", getattr(partition, "test_set", None), self.config.apply_to_test),
            ("local_test", getattr(partition, "local_test_set", None), self.config.apply_to_local_test),
        ):
            if enabled:
                self._transform_dataset(dataset, name, seen_data)

    def _transform_dataset(self, dataset, name: str, seen_data: set[int]) -> None:
        # Transform all samples in one dataset split, avoiding duplicated shared data.
        data = getattr(dataset, "data", None)
        if dataset is None or data is None:
            return

        if id(data) in seen_data:
            logging.info("[FeatureSqueezingDefense] Dataset %s already transformed; skipping duplicate data", name)
            self._log_check(data, name, status="already_transformed")
            return

        before_sample = data[0] if len(data) else None
        before = self._summary(before_sample) if before_sample is not None else None
        for idx, sample in enumerate(data):
            data[idx] = self._transform_sample(sample)

        seen_data.add(id(data))
        logging.info("[FeatureSqueezingDefense] Transformed %s samples in %s set", len(data), name)
        self._log_check(data, name, status="transformed", before=before)

    def _transform_sample(self, sample):
        # Transform only the input image and keep labels or metadata unchanged.
        if isinstance(sample, tuple) and sample:
            return (self._squeeze_image(sample[0]), *sample[1:])
        return self._squeeze_image(sample)

    # ------------------------------------------------------------------
    # Image squeezing
    # ------------------------------------------------------------------

    def _squeeze_image(self, value):
        # Quantize PIL images, tensors, and arrays while preserving the original container type.
        if isinstance(value, Image.Image):
            image = value if value.mode in PIL_IMAGE_MODES else value.convert("RGB")
            arr = np.asarray(image)
            squeezed = np.rint(self._squeeze_image_array(arr)).clip(0, 255).astype(arr.dtype, copy=False)
            return Image.fromarray(squeezed, mode=image.mode)

        squeezed = self._squeeze_image_array(self._as_numpy(value))
        return self._restore_type(value, squeezed)

    def _squeeze_image_array(self, arr: np.ndarray) -> np.ndarray:
        # Normalize values to [0, 1], quantize them, and map them back to the original range.
        arr_float = arr.astype(np.float32, copy=False)
        if np.issubdtype(arr.dtype, np.integer):
            info = np.iinfo(arr.dtype)
            low, high = float(info.min), float(info.max)
        else:
            low, high = float(np.nanmin(arr_float)), float(np.nanmax(arr_float))
            if low >= 0.0 and high <= 1.0:
                low, high = 0.0, 1.0

        value_range = high - low
        if value_range == 0:
            return arr.copy()
        return self._quantize01((arr_float - low) / value_range) * value_range + low

    # ------------------------------------------------------------------
    # Helpers and diagnostics
    # ------------------------------------------------------------------

    def _quantize01(self, arr: np.ndarray) -> np.ndarray:
        # Reduce normalized values to the discrete levels defined by bit_depth.
        return np.rint(np.clip(arr, 0.0, 1.0) * self.levels) / self.levels

    def _log_check(self, data, name: str, status: str, before: str | None = None) -> None:
        # Log a compact before/after summary to verify that squeezing was applied.
        if not len(data):
            logging.info("[FeatureSqueezingDefense] Verification %s | status=%s | empty dataset", name, status)
            return

        expectation = f"expected_unique_values<={int(self.levels + 1)}"

        after = self._summary(data[0])
        if before is None:
            logging.info(
                "[FeatureSqueezingDefense] Verification %s | status=%s | %s | sample_after={%s}",
                name,
                status,
                expectation,
                after,
            )
            return

        logging.info(
            "[FeatureSqueezingDefense] Verification %s | status=%s | %s | sample_before={%s} | "
            "sample_after={%s}",
            name,
            status,
            expectation,
            before,
            after,
        )

    def _summary(self, sample) -> str:
        # Create a short numeric summary of one sample for diagnostics.
        arr = self._as_numpy(self._unwrap(sample))
        if arr.size == 0:
            return f"shape={arr.shape}, empty=True"

        flat = arr.reshape(-1)
        unique = np.unique(flat)
        preview = ", ".join(self._fmt(value) for value in unique[: min(12, len(unique))])
        return (
            f"shape={arr.shape}, dtype={arr.dtype}, min={self._fmt(np.nanmin(flat))}, "
            f"max={self._fmt(np.nanmax(flat))}, unique_count={len(unique)}, unique_preview=[{preview}]"
        )

    def _as_numpy(self, value) -> np.ndarray:
        # Convert supported image containers to numpy for quantization and logging.
        if isinstance(value, torch.Tensor):
            return value.detach().cpu().numpy()
        if isinstance(value, Image.Image):
            return np.asarray(value)
        return np.asarray(value)

    def _restore_type(self, original, arr: np.ndarray):
        # Return squeezed data with the same high-level type as the original sample.
        if isinstance(original, torch.Tensor):
            return torch.as_tensor(arr, dtype=original.dtype, device=original.device)
        if isinstance(original, np.ndarray):
            return arr.astype(original.dtype, copy=False)
        return arr

    def _unwrap(self, sample):
        # Extract the image from common dataset samples shaped as (image, label, ...).
        return sample[0] if isinstance(sample, tuple) and sample else sample

    def _fmt(self, value) -> str:
        # Format numbers in logs without unnecessary trailing decimals.
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        return str(int(number)) if number.is_integer() else f"{number:.6g}"


def apply_feature_squeezing_if_enabled(partition, participant_config: dict[str, Any]) -> None:
    # Public entrypoint used by the node startup flow.
    defense = FeatureSqueezingDefense.from_participant_config(participant_config)
    if defense is not None:
        defense.apply_to_partition(partition)
