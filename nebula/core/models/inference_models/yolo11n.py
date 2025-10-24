import copy
import traceback
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union
from nebula.core.datasets.hackaton.dataset import prepare_dataset, write_dataset_yaml
from nebula.core.models.inference_models.config.config import ensure_dual_head_config, update_model_cfg
from nebula.core.models.inference_models.patch import ensure_ultralytics_multihead_support
from nebula.core.models.nebulamodel import NebulaModel
from ultralytics import YOLO
from pathlib import Path
import yaml
import torch
import logging

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

class YOLO11n(NebulaModel):
    def __init__(
        self,
        input_channels=1,
        num_classes=10,
        learning_rate=1e-3,
        metrics=None,
        confusion_matrix=None,
        seed=None,
    ):
        super().__init__(input_channels, num_classes, learning_rate, metrics, confusion_matrix, seed)
        self._dataset_initialized = False 
        self._base_model_path = Path("/home/dietpi/prueba/nebula/nebula/core/models/inference_models/yolo11n.pt")
        self._model = YOLO(self._base_model_path)
        self._freeze_layers = 23
        self._head_module_index = self._detect_last_head_index()
        self._new_class_names = ["shoes"]
        self._config_path: Path = Path("/home/dietpi/prueba/nebula/nebula/core/models/inference_models/config/yolo11n-2xhead.yaml")
        
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
        #TODO ver cuantos samples hay en el dataset
        pass
    
    def _update_head(self, head_state, freeze_layers):
        """
        Actualiza el modelo local añadiendo una nueva cabeza.
        head_state: dict con los pesos de la cabeza (enviados desde otro nodo)
        freeze_layers: número de capas congeladas (para localizar la cabeza)
        """
        try:
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
            ensure_dual_head_config(Path("/home/dietpi/prueba/nebula/nebula/core/models/inference_models/config/yolo11n-2xhead.yaml"))
            class_names, class_mapping, splits = prepare_dataset(
                Path("/home/dietpi/prueba/nebula/nebula/core/datasets/hackaton/datasets/shoes"), 
                Path("/home/dietpi/prueba/nebula/nebula/core/datasets/hackaton/processed/shoes"), 
                "shoes", 
                None)
            logging.info("Detected class ids: %s", class_mapping)
            logging.info("Using class names: %s", class_names)

            write_dataset_yaml(
                Path("/home/dietpi/prueba/nebula/nebula/core/datasets/hackaton/datasets/dataset.yaml"), 
                Path("/home/dietpi/prueba/nebula/nebula/core/datasets/hackaton/processed/shoes"), 
                class_names, 
                splits)

            added_classes = len(class_names)
            update_model_cfg(
                Path("/home/dietpi/prueba/nebula/nebula/core/models/inference_models/config/yolo11n-2xhead.yaml"), 
                added_classes, 
                base_class_count=80)
            
            self._train_and_merge(
                new_class_names=class_names,
            )
        else:
            self._train_and_merge()    
        
    def build_full_class_names(self, new_class_names: Sequence[str]) -> list[str]:
        """Concatenate the default COCO names with the new dataset-specific names."""

        return list(COCO_NAMES) + list(new_class_names)    
        
    def _train_and_merge(
    self,
    config_path: Path = Path("/home/dietpi/prueba/nebula/nebula/core/models/inference_models/config/yolo11n-2xhead.yaml"),
    data_yaml: Path = Path("/home/dietpi/prueba/nebula/nebula/core/datasets/hackaton/dataset.yaml"),
    new_class_names: Sequence[str] = ['shoes'],
    freeze_layers: int = 23,
    epochs: int = 30,
    imgsz: int = 320,
    batch_size: int = 2,
    output_dir: Path = Path("/home/dietpi/prueba/nebula/app/logs/inference_experiment"),
    dataset_name: str = "shoes",
    base_model: str = "/home/dietpi/prueba/nebula/nebula/core/models/inference_models/yolo11n.pt",
) -> Dict[str, Path | None]:

        output_dir.mkdir(parents=True, exist_ok=True)

        model = YOLO(base_model)
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

        project_dir = output_dir / "runs"
        project_dir.mkdir(parents=True, exist_ok=True)

        results = model.train(
            data=str(data_yaml),
            freeze=freeze_layers,
            epochs=epochs,
            imgsz=imgsz,
            batch=batch_size,
            project=str(project_dir),
            name=dataset_name,
            exist_ok=True,
        )

        trainer = getattr(model, "trainer", None)
        if trainer is not None and getattr(trainer, "save_dir", None):
            save_dir = Path(trainer.save_dir)
        elif hasattr(results, "save_dir"):
            save_dir = Path(results.save_dir)
        else:
            save_dir = project_dir / dataset_name

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

        head_weights_path = output_dir / f"{Path(base_model).stem}_{dataset_name}_head.pth"
        torch.save(head_weights, head_weights_path)

        merged_model = YOLO(str(config_path), task="detect").load(base_model)

        state_dict = torch.load(head_weights_path, map_location="cpu")
        missing, unexpected = merged_model.load_state_dict(state_dict, strict=False)

        merged_model.model.names = {idx: name for idx, name in enumerate(self.build_full_class_names(new_class_names))}
        merged_model.ckpt = {"model": merged_model.model}

        merged_weights_path = output_dir / f"{Path(base_model).stem}_{dataset_name}_merged.pt"
        merged_model.save(str(merged_weights_path))
        
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
