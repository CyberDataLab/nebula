"""
Helpers for generating and updating the dual-head YOLO configuration file.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path


logger = logging.getLogger(__name__)


def ensure_dual_head_config(config_path: Path) -> None:
    """
    Create a YOLO11 dual-head config file if it does not already exist. The base template
    is copied from the installed Ultralytics package.
    """

    if config_path.exists():
        return

    import ultralytics

    base_cfg = Path(ultralytics.__file__).resolve().parent / "cfg" / "models" / "11" / "yolo11.yaml"
    if not base_cfg.exists():
        raise FileNotFoundError(f"Base YOLO11 config not found: {base_cfg}")

    base_text = base_cfg.read_text()
    modified = base_text.replace("nc: 80 # number of classes", "nc: 82 # number of classes", 1)
    modified = modified.replace(
        "  - [[16, 19, 22], 1, Detect, [nc]] # Detect(P3, P4, P5)",
        "\n".join(
            (
                "  - [[16, 19, 22], 1, Detect, [80]] # Base COCO head",
                "  - [[16, 19, 22], 1, Detect, [2]] # Added classes head",
                "  - [[23, 24], 1, ConcatHead, [80, 2]] # Merge detection heads",
            )
        ),
        1,
    )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(modified)
    logger.info("Created dual-head config at %s", config_path)


def update_model_cfg(cfg_path: Path, added_classes: int, base_class_count: int) -> Path:
    """
    Adjust the dual-head config to account for a custom number of new classes.

    Parameters
    ----------
    cfg_path:
        Path to the configuration file.
    added_classes:
        Number of custom classes in the dataset.
    base_class_count:
        Number of classes provided by the pretrained model (COCO = 80).
    """

    content = cfg_path.read_text()
    total_classes = base_class_count + added_classes
    content, replaced_nc = re.subn(
        r"nc:\s+\d+\s+# number of classes",
        f"nc: {total_classes} # number of classes",
        content,
        count=1,
    )
    if replaced_nc == 0:
        raise ValueError(f"Failed to update class count in {cfg_path}")

    content, replaced_detect = re.subn(
        r"  - \[\[16, 19, 22\], 1, Detect, \[\d+\]\] # Added classes head",
        f"  - [[16, 19, 22], 1, Detect, [{added_classes}]] # Added classes head",
        content,
        count=1,
    )
    if replaced_detect == 0:
        raise ValueError(f"Failed to update new head definition in {cfg_path}")

    content, replaced_concat = re.subn(
        r"  - \[\[23, 24\], 1, ConcatHead, \[80, \d+\]\] # Merge detection heads",
        f"  - [[23, 24], 1, ConcatHead, [80, {added_classes}]] # Merge detection heads",
        content,
        count=1,
    )
    if replaced_concat == 0:
        raise ValueError(f"Failed to update ConcatHead definition in {cfg_path}")

    cfg_path.write_text(content)
    logger.info("Configured %s for %s new classes (%s total).", cfg_path, added_classes, total_classes)
    return cfg_path
