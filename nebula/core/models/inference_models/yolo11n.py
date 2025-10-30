import copy
import os
import traceback
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

import logging
import torch
import yaml
from ultralytics import YOLO

from nebula.core.datasets.hackaton.dataset import prepare_dataset, write_dataset_yaml
from nebula.core.models.inference_models.config.config import ensure_dual_head_config, update_model_cfg
from nebula.core.models.inference_models.patch import ensure_ultralytics_multihead_support
from nebula.core.models.nebulamodel import NebulaModel

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

IMAGE_EXTENSIONS: tuple[str, ...] = (
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
)

class YOLO11n(NebulaModel):
    def __init__(
        self,
        input_channels=1,
        num_classes=10,
        learning_rate=1e-3,
        metrics=None,
        confusion_matrix=None,
        malicious: Optional[bool] = None,
        poison_label: str = "spoon",
        seed=None,
    ):
        super().__init__(input_channels, num_classes, learning_rate, metrics, confusion_matrix, seed)
        self._dataset_initialized = False
        module_dir = Path(__file__).resolve().parent
        self._project_root = self._discover_project_root(module_dir)
        self._node_id, self._num_nodes = self._load_node_partition_config()
        self._base_model_path = self._project_root / "nebula/core/models/inference_models/yolo11n.pt"
        self._model = YOLO(str(self._base_model_path))
        self._freeze_layers = 23
        self._head_module_index = self._detect_last_head_index()
        self._poison_label_name = (poison_label or "spoon").strip().lower()
        self._poison_logged_once = False
        self._new_class_names = ["drones"]
        self._config_path: Path = self._project_root / "nebula/core/models/inference_models/config/yolo11n-2xhead.yaml"
        dataset_root = self._project_root / "nebula/core/datasets/hackaton"
        dataset_yaml_name = self._build_dataset_yaml_name(self._node_id, self._num_nodes)
        self._data_yaml_path: Path = dataset_root / "datasets" / dataset_yaml_name
        if self._node_id is not None:
            logging.info(
                "Dataset partitioning enabled for node_id=%s over %s nodes. Using dataset YAML %s.",
                self._node_id,
                self._num_nodes,
                self._data_yaml_path,
            )
        self._model_weight: int = 1
        self._dataset_name: str = "drones"
        self._logs_root: Path = self._project_root / "app/logs/inference_experiment"
        
    def _discover_project_root(self, start_dir: Path) -> Path:
        markers = ("pyproject.toml", ".git")
        for candidate in [start_dir, *start_dir.parents]:
            if any((candidate / marker).exists() for marker in markers):
                return candidate
        parent_list = list(start_dir.parents)
        fallback = parent_list[-1] if parent_list else start_dir
        logging.warning(
            "Failed to locate project root markers; defaulting project root to %s.",
            fallback,
        )
        return fallback

    def _parse_env_int(self, key: str) -> int | None:
        value = os.environ.get(key)
        if value is None or value == "":
            return None
        try:
            return int(value)
        except ValueError:
            logging.warning("Environment variable %s should be an integer, got %r. Ignoring.", key, value)
            return None

    def _load_node_partition_config(self) -> tuple[int | None, int | None]:
        node_id = self._parse_env_int("NEBULA_NODE_ID")
        num_nodes = self._parse_env_int("NEBULA_NUM_NODES")
        if (node_id is None) ^ (num_nodes is None):
            logging.warning(
                "Both NEBULA_NODE_ID and NEBULA_NUM_NODES must be set to enable dataset partitioning. "
                "Received node_id=%s, num_nodes=%s. Ignoring node partition configuration.",
                node_id,
                num_nodes,
            )
            return None, None
        if node_id is not None and num_nodes is not None:
            if num_nodes <= 0:
                logging.warning("NEBULA_NUM_NODES must be positive (got %s). Ignoring node partition configuration.", num_nodes)
                return None, None
            if node_id < 0 or node_id >= num_nodes:
                logging.warning(
                    "NEBULA_NODE_ID must be in [0, %s] (got %s). Ignoring node partition configuration.",
                    num_nodes - 1,
                    node_id,
                )
                return None, None
        return node_id, num_nodes

    def _build_dataset_yaml_name(self, node_id: int | None, num_nodes: int | None) -> str:
        if node_id is not None and num_nodes is not None:
            return f"dataset_node_{node_id}_of_{num_nodes}.yaml"
        return "dataset.yaml"
        
    def _detect_last_head_index(self) -> int | None:
        modules = getattr(self._model.model, "model", None)
        if modules is None:
            return None
        detect_indices = [
            idx for idx, module in enumerate(modules)
            if module.__class__.__name__ == "Detect"
        ]
        return detect_indices[-1] if detect_indices else None
        
    def load_state_dict(self, params):
        try:
            current_state = self._model.model.state_dict()
            param_keys = set(params.keys())
            current_keys = set(current_state.keys())

            if any(key.startswith("model.model.") for key in param_keys):
                self._update_head(params, self._freeze_layers)
                return

            unknown_keys = param_keys - current_keys

            if unknown_keys:
                self._update_head(params, self._freeze_layers)
            else:
                current_state.update(params)
                self._model.model.load_state_dict(current_state, strict=False)
        except Exception as e:
            logging.error(traceback.format_exc())       
        
    def get_model_parameters(self):
        head_index = self._head_module_index
        if head_index is None:
            head_index = self._detect_last_head_index()
            self._head_module_index = head_index
        if head_index is None:
            return {}

        state_dict = self._model.model.state_dict()
        prefix = f"model.{head_index}"
        head_items: Dict[str, torch.Tensor] = {}
        for name, tensor in state_dict.items():
            if not name.startswith(prefix):
                continue
            adjusted_name = name.replace("model.", "model.model.", 1)
            head_items[adjusted_name] = tensor.clone()
        return head_items
    
    def get_model_weight(self):
        return self._model_weight

    def _update_model_weight(self, data_yaml: Path) -> None:
        try:
            data_config = yaml.safe_load(data_yaml.read_text())
        except FileNotFoundError:
            logging.warning("Data YAML not found at %s; keeping existing model weight.", data_yaml)
            return
        except Exception:
            logging.warning("Failed to parse data YAML at %s; keeping existing model weight.", data_yaml, exc_info=True)
            return

        train_path_str = data_config.get("train")
        if not train_path_str:
            logging.warning("Data YAML %s does not define a 'train' path; keeping existing model weight.", data_yaml)
            return

        train_path = Path(train_path_str)
        if not train_path.exists():
            logging.warning("Training directory %s does not exist; keeping existing model weight.", train_path)
            return

        sample_count = sum(
            1
            for candidate in train_path.rglob("*")
            if candidate.is_file() and candidate.suffix.lower() in IMAGE_EXTENSIONS
        )

        if sample_count == 0:
            labels_root = train_path.parents[1] / "labels" / train_path.name
            if labels_root.exists():
                sample_count = sum(1 for candidate in labels_root.rglob("*.txt") if candidate.is_file())

        if sample_count == 0:
            logging.warning("Unable to infer dataset size from %s; keeping existing model weight.", data_yaml)
            return

        self._model_weight = int(sample_count)
        logging.info("Updated model weight to %s samples based on %s.", self._model_weight, train_path)
    
    def _update_head(self, head_state, freeze_layers):
        """
        Actualiza el modelo local añadiendo una nueva cabeza.
        head_state: dict con los pesos de la cabeza (enviados desde otro nodo)
        freeze_layers: número de capas congeladas (para localizar la cabeza)
        """
        try:
            ensure_ultralytics_multihead_support()
            base_model_path = str(self._base_model_path)
            if self._config_path and self._config_path.exists():
                merged_model = YOLO(str(self._config_path), task="detect").load(base_model_path)
            else:
                merged_model = YOLO(base_model_path)

            merged_model.model.load_state_dict(self._model.model.state_dict(), strict=False)

            remapped_head = {
                key.replace("model.model.", "model.", 1): value
                for key, value in head_state.items()
            }

            missing, unexpected = merged_model.model.load_state_dict(remapped_head, strict=False)
            if missing:
                logging.debug("Missing keys during head merge: {0}".format(missing))
            if unexpected:
                logging.debug("Unexpected keys during head merge: {0}".format(unexpected))

            if hasattr(merged_model.model, "freeze"):
                merged_model.model.freeze(freeze_layers)
            else:
                for idx, module in enumerate(getattr(merged_model.model, "model", [])[:freeze_layers]):
                    for param in module.parameters():
                        param.requires_grad = False

            custom_names = self._new_class_names if self._new_class_names else ["custom"]
            merged_model.model.names = {
                idx: name for idx, name in enumerate(self.build_full_class_names(custom_names))
            }
            merged_model.ckpt = {"model": merged_model.model}

            self._model = merged_model
            self._head_module_index = self._detect_last_head_index()

        except Exception as e:
            logging.error(traceback.format_exc())
                
    def train(self):
        if not self._dataset_initialized:
            ensure_ultralytics_multihead_support()
            ensure_dual_head_config(self._config_path)
            dataset_root = self._project_root / "nebula/core/datasets/hackaton"
            raw_dataset_path = dataset_root / "datasets" / self._dataset_name
            processed_dataset_path = dataset_root / "processed" / self._dataset_name
            dataset_yaml_path = self._data_yaml_path
            class_names, class_mapping, splits = prepare_dataset(
                raw_dataset_path,
                processed_dataset_path,
                self._dataset_name,
                None,
            )
            logging.info("Detected class ids: %s", class_mapping)
            logging.info("Using class names: %s", class_names)

            write_dataset_yaml(
                dataset_yaml_path,
                processed_dataset_path,
                class_names,
                splits,
                node_id=self._node_id,
                num_nodes=self._num_nodes,
            )

            added_classes = len(class_names)
            update_model_cfg(
                self._config_path,
                added_classes,
                base_class_count=80,
            )
            self._new_class_names = list(class_names)

            best_weights, head_weights, merged_weights = self._train_and_merge(
                config_path=self._config_path,
                data_yaml=dataset_yaml_path,
                new_class_names=class_names,
                dataset_name=self._dataset_name,
            )
            self._dataset_initialized = True
            self._data_yaml_path = dataset_yaml_path
            logging.info(f"Train and merge: best_weights {best_weights}, head_weights {head_weights} and merged_weights {merged_weights}")
        else:
            best_weights, head_weights, merged_weights = self._train_and_merge(
                config_path=self._config_path,
                data_yaml=self._data_yaml_path,
                new_class_names=self._new_class_names,
                dataset_name=self._dataset_name,
            )

    def _poison_labels_callback(self, trainer):
        """
        En cada batch de entrenamiento, si _is_malicious está activo:
        cambia todas las anotaciones con clase 'drones' a la clase destino por nombre.
        """
        if not self._is_malicious:
            return

        batch = getattr(trainer, "batch", None)
        if not batch or "cls" not in batch:
            return

        # cls viene como float (N,1); convertimos a long para comparar/setear índices
        cls = batch["cls"].view(-1).to(dtype=torch.long)

        # Resolución de nombres de clase
        names = getattr(trainer.model, "names", None)
        if names is None:
            data = getattr(trainer, "data", None)
            names = getattr(data, "names", None)

        # Normaliza nombres -> id
        name_to_id = {}
        if isinstance(names, (list, tuple)):
            name_to_id = {str(n).strip().lower(): i for i, n in enumerate(names)}
        elif isinstance(names, dict):
            # Algunas versiones usan {id: name}
            try:
                name_to_id = {str(v).strip().lower(): int(k) for k, v in names.items()}
            except Exception:
                # Otras usan {name: id}
                name_to_id = {str(k).strip().lower(): int(v) for k, v in names.items()}

        # IDs de la clase origen
        drone_aliases = ["drones", "drone", "uav"]
        drone_ids = [name_to_id[n] for n in drone_aliases if n in name_to_id]

        # Caso de data.yaml con una única clase que sea 'drones'
        if not drone_ids and isinstance(names, (list, tuple)) and len(names) == 1:
            if str(names[0]).strip().lower() in drone_aliases:
                drone_ids = [0]

        if not drone_ids:
            if not self._poison_º_once:
                logging.warning("[POISON] Clase 'drones' no encontrada en names=%r. Sin cambios.", names)
                self._poison_logged_once = True
            return

        src_id = int(drone_ids[0])

        # Clase destino
        dst_id = name_to_id.get(self._poison_label_name)
        if dst_id is None:
            # Fallback: 'spoon' suele ser 44 en COCO; si no, 0
            if isinstance(names, (list, tuple)) and len(names) >= 45:
                dst_id = 44
            else:
                dst_id = 0

        mask = (cls == src_id)
        if mask.any():
            cls[mask] = int(dst_id)
            batch["cls"] = cls.view(-1, 1).to(dtype=torch.float32)
            trainer.batch = batch

            if not self._poison_logged_once:
                logging.info(
                    "[POISON] Re-etiquetando '%s'(id=%d) -> '%s'(id=%d) en %d anotaciones (cliente malicioso).",
                    "drones", src_id, self._poison_label_name, dst_id, int(mask.sum().item())
                )
                self._poison_logged_once = True


    def build_full_class_names(self, new_class_names: Sequence[str]) -> list[str]:
        """Concatenate the default COCO names with the new dataset-specific names."""

        return list(COCO_NAMES) + list(new_class_names)    
        
    def _train_and_merge(
        self,
        config_path: Path | None = None,
        data_yaml: Path | None = None,
        new_class_names: Sequence[str] | None = None,
        freeze_layers: int = 23,
        epochs: int = 2,
        imgsz: int = 640,
        batch_size: int = 4,
        output_dir: Path | None = None,
        dataset_name: str | None = None,
        base_model: str | Path | None = None,
    ) -> Dict[str, Path | None]:

        resolved_output_dir = output_dir or self._logs_root
        resolved_output_dir.mkdir(parents=True, exist_ok=True)

        model_path = Path(base_model) if base_model else self._base_model_path
        config_path = Path(config_path) if config_path else self._config_path
        data_yaml_path = Path(data_yaml) if data_yaml else self._data_yaml_path
        class_names = new_class_names or self._new_class_names
        run_name = dataset_name or self._dataset_name
        model = YOLO(str(model_path))
        original_state = copy.deepcopy(model.state_dict())
        head_prefix = f"model.model.{freeze_layers}"

        def put_in_eval_mode(trainer, n_layers: int = freeze_layers) -> None:
            model_ref = getattr(trainer, "model", None)
            if model_ref is None or not hasattr(model_ref, "named_modules"):
                return
            for name, module in model_ref.named_modules():
                if not name.endswith("bn"):
                    continue
                parts = [part for part in name.split(".") if part.isdigit()]
                if not parts:
                    continue
                layer_idx = int(parts[0])
                if layer_idx < n_layers and hasattr(module, "track_running_stats"):
                    module.eval()
                    module.track_running_stats = False

        model.add_callback("on_train_epoch_start", put_in_eval_mode)
        model.add_callback("on_pretrain_routine_start", put_in_eval_mode)
        if self._is_malicious:
            # Se engancha al inicio de cada batch de entrenamiento
            model.add_callback("on_train_batch_start", self._poison_labels_callback)
            logging.warning("[POISON] Malicious node changing labels from drones to -> '%s'.",
                            self._poison_label_name)
        
        project_dir = resolved_output_dir / "runs"
        project_dir.mkdir(parents=True, exist_ok=True)

        results = model.train(
            data=str(data_yaml_path),
            freeze=freeze_layers,
            epochs=epochs,
            imgsz=imgsz,
            batch=batch_size,
            project=str(project_dir),
            name=run_name,
            exist_ok=True,
        )

        trainer = getattr(model, "trainer", None)
        if trainer is not None and getattr(trainer, "save_dir", None):
            save_dir = Path(trainer.save_dir)
        elif hasattr(results, "save_dir"):
            save_dir = Path(results.save_dir)
        else:
            save_dir = project_dir / run_name

        best_weights = save_dir / "weights" / "best.pt"

        updated_state = model.state_dict()
        for key, tensor in original_state.items():
            if key not in updated_state:
                continue
            if tensor.shape != updated_state[key].shape:
                continue
            if not torch.equal(tensor, updated_state[key]) and "bn" in key and head_prefix not in key:
                updated_state[key] = tensor

        head_weights: Dict[str, torch.Tensor] = {}
        for key, tensor in updated_state.items():
            if key.startswith(head_prefix):
                renamed = key.replace(f".{freeze_layers}", f".{freeze_layers + 1}", 1)
                head_weights[renamed] = tensor.clone()

        stem = model_path.stem
        head_weights_path = resolved_output_dir / f"{stem}_{run_name}_head.pth"
        torch.save(head_weights, head_weights_path)

        merged_model = YOLO(str(config_path), task="detect").load(str(model_path))

        state_dict = torch.load(head_weights_path, map_location="cpu")
        missing, unexpected = merged_model.load_state_dict(state_dict, strict=False)

        merged_model.model.names = {idx: name for idx, name in enumerate(self.build_full_class_names(class_names))}
        merged_model.ckpt = {"model": merged_model.model}

        merged_weights_path = resolved_output_dir / f"{stem}_{run_name}_merged.pt"
        merged_model.save(str(merged_weights_path))
        
        self._update_model_weight(data_yaml_path)
        self._model = merged_model

        return {
            "best_weights": best_weights,
            "head_weights": head_weights_path,
            "merged_weights": merged_weights_path,
        }

    def forward(self, x):
        """Forward pass of the model."""
        pass

    def configure_optimizers(self):
        """Optimizer configuration."""
        pass
