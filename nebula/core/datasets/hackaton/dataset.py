"""
Dataset preparation helpers: remapping class IDs, mirroring the dataset structure,
and generating the data.yaml file required by Ultralytics.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Dict, List, Sequence


logger = logging.getLogger(__name__)

COCO_NAMES: tuple[str, ...] = (
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "airplane",
    "bus",
    "train",
    "truck",
    "boat",
    "traffic light",
    "fire hydrant",
    "stop sign",
    "parking meter",
    "bench",
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
    "backpack",
    "umbrella",
    "handbag",
    "tie",
    "suitcase",
    "frisbee",
    "skis",
    "snowboard",
    "sports ball",
    "kite",
    "baseball bat",
    "baseball glove",
    "skateboard",
    "surfboard",
    "tennis racket",
    "bottle",
    "wine glass",
    "cup",
    "fork",
    "knife",
    "spoon",
    "bowl",
    "banana",
    "apple",
    "sandwich",
    "orange",
    "broccoli",
    "carrot",
    "hot dog",
    "pizza",
    "donut",
    "cake",
    "chair",
    "couch",
    "potted plant",
    "bed",
    "dining table",
    "toilet",
    "tv",
    "laptop",
    "mouse",
    "remote",
    "keyboard",
    "cell phone",
    "microwave",
    "oven",
    "toaster",
    "sink",
    "refrigerator",
    "book",
    "clock",
    "vase",
    "scissors",
    "teddy bear",
    "hair drier",
    "toothbrush",
)


def symlink_or_copy(src: Path, dst: Path) -> None:
    """Create a symlink where possible, otherwise fall back to copying."""

    if dst.exists():
        return
    try:
        dst.symlink_to(src)
    except OSError:
        shutil.copy2(src, dst)


def collect_class_ids(label_dir: Path) -> List[int]:
    """Return a sorted list of class IDs present in YOLO label files."""

    class_ids = set()
    for label_file in label_dir.glob("*.txt"):
        with label_file.open() as handle:
            for line in handle:
                stripped = line.strip()
                if stripped:
                    class_ids.add(int(stripped.split()[0]))
    return sorted(class_ids)


def prepare_dataset(
    src_dir: Path,
    processed_dir: Path,
    dataset_name: str,
    class_names_override: Sequence[str] | None = None,
) -> tuple[List[str], Dict[int, int], List[str]]:
    """
    Remap class IDs to a dense range starting at zero and mirror the dataset structure
    under ``processed_dir``. Files are symlinked when possible to minimise duplication.
    """

    if not src_dir.exists():
        raise FileNotFoundError(f"Dataset directory not found: {src_dir}")

    image_root = src_dir / "images"
    label_root = src_dir / "labels"
    if not image_root.exists() or not label_root.exists():
        raise FileNotFoundError(f"Expected 'images' and 'labels' directories in {src_dir}")

    splits = [p.name for p in image_root.iterdir() if p.is_dir()]
    if not splits:
        raise ValueError(f"No dataset splits found under {image_root}")

    all_class_ids: set[int] = set()
    for split in splits:
        split_dir = label_root / split
        if split_dir.exists():
            all_class_ids.update(collect_class_ids(split_dir))

    if not all_class_ids:
        raise ValueError(f"No labels found in {label_root}")

    sorted_ids = sorted(all_class_ids)
    class_mapping = {original: idx for idx, original in enumerate(sorted_ids)}

    if class_names_override:
        if len(class_names_override) != len(sorted_ids):
            raise ValueError(
                f"Provided {len(class_names_override)} class names but dataset exposes {len(sorted_ids)} unique IDs."
            )
        class_names = list(class_names_override)
    else:
        slug = dataset_name.replace(" ", "_").replace("-", "_")
        class_names = [slug] if len(sorted_ids) == 1 else [f"{slug}_{idx}" for idx in range(len(sorted_ids))]

    if processed_dir.exists():
        shutil.rmtree(processed_dir)
    processed_images_root = processed_dir / "images"
    processed_labels_root = processed_dir / "labels"

    for split in splits:
        src_images_split = image_root / split
        src_labels_split = label_root / split
        dst_images_split = processed_images_root / split
        dst_labels_split = processed_labels_root / split

        dst_images_split.mkdir(parents=True, exist_ok=True)
        dst_labels_split.mkdir(parents=True, exist_ok=True)

        label_lookup = {p.name: p for p in src_labels_split.glob("*.txt")} if src_labels_split.exists() else {}

        for image_path in sorted(src_images_split.glob("*")):
            if not image_path.is_file():
                continue

            dst_image_path = dst_images_split / image_path.name
            symlink_or_copy(image_path.resolve(), dst_image_path)

            label_filename = image_path.with_suffix(".txt").name
            src_label = label_lookup.get(label_filename)
            dst_label = dst_labels_split / label_filename

            if src_label is None:
                dst_label.write_text("")
                continue

            remapped_lines: List[str] = []
            with src_label.open() as label_handle:
                for line in label_handle:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    parts = stripped.split()
                    original_cls = int(parts[0])
                    if original_cls not in class_mapping:
                        raise ValueError(f"Unexpected class ID {original_cls} in {src_label}")
                    parts[0] = str(class_mapping[original_cls])
                    remapped_lines.append(" ".join(parts))

            dst_label.write_text("\n".join(remapped_lines) + ("\n" if remapped_lines else ""))

    processed_dir.mkdir(parents=True, exist_ok=True)
    mapping_path = processed_dir / "class_mapping.json"
    mapping_path.write_text(
        json.dumps(
            {
                "source_dataset": str(src_dir.resolve()),
                "class_id_map": {str(k): v for k, v in class_mapping.items()},
                "class_names": class_names,
            },
            indent=2,
        )
    )

    logger.debug("Prepared dataset at %s (classes: %s)", processed_dir, class_mapping)
    return class_names, class_mapping, splits


def select_split(splits: Sequence[str], target: str) -> str | None:
    """Return the dataset split that matches ``target``, accounting for common aliases."""

    if target in splits:
        return target
    aliases = {"val": ["val", "valid", "validation"], "test": ["test", "testing"]}
    for alias in aliases.get(target, []):
        if alias in splits:
            return alias
    return None


def write_dataset_yaml(
    yaml_path: Path,
    processed_dir: Path,
    class_names: Sequence[str],
    splits: Sequence[str],
) -> Path:
    """Generate a YOLO ``data.yaml`` file pointing to the processed dataset."""

    processed_dir = processed_dir.resolve()
    train_split = select_split(splits, "train")
    val_split = select_split(splits, "val")
    test_split = select_split(splits, "test")

    if train_split is None:
        raise ValueError("Dataset must include a 'train' split")
    if val_split is None:
        raise ValueError("Dataset must include a validation split ('val' or 'valid')")

    lines = [
        "# Auto-generated by src/train.py",
        f"path: {processed_dir}",
        f"train: {processed_dir / 'images' / train_split}",
        f"val: {processed_dir / 'images' / val_split}",
    ]
    if test_split is not None:
        lines.append(f"test: {processed_dir / 'images' / test_split}")
    lines.append(f"nc: {len(class_names)}")
    lines.append("names:")
    for name in class_names:
        lines.append(f"  - {name}")

    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text("\n".join(lines) + "\n")
    logger.debug("Wrote dataset YAML to %s", yaml_path)
    return yaml_path
