from typing import Any, Dict, Iterable, List, Optional, Union
from nebula.core.models.nebulamodel import NebulaModel
from ultralytics import YOLO
from pathlib import Path
import yaml

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
        self._model = YOLO("yolo11n.pt")
        self._freezed_value = 22
        self._freeze_applied = False
        self._data_path = ""
        self._training_config = self._build_config()
        

    def _resolve_freeze_indices(self, model, freeze_value: Union[int, List[int], str, None]) -> List[int]:
        if freeze_value is None:
            return []

        modules = list(model.model.model)  # type: ignore[attr-defined]
        total = len(modules)

        if isinstance(freeze_value, int):
            return [idx for idx in range(freeze_value) if 0 <= idx < total]

        if isinstance(freeze_value, str):
            if freeze_value.lower() != "backbone":
                raise ValueError(
                    "Sólo se reconoce la palabra clave 'backbone' para congelar de forma automática."
                )
            # Congela todo hasta el primer módulo de la cabeza (justo antes del primer Upsample/C2*).
            head_markers = {"C2PSA", "C2f", "Detect", "DetectQ", "Pose", "Segment", "OBBDetect"}
            cutoff: Optional[int] = next(
                (idx for idx, module in enumerate(modules) if module.__class__.__name__ in head_markers),
                None,
            )
            if cutoff is None:
                cutoff = next(
                    (idx for idx, module in enumerate(modules) if module.__class__.__name__ == "Upsample"),
                    None,
                )
            if cutoff is None or cutoff <= 0 or cutoff >= total:
                cutoff = max(0, total - 3)  # deja al menos los tres últimos módulos entrenables
            return list(range(cutoff))

        if isinstance(freeze_value, Iterable):
            indices: List[int] = []
            for value in freeze_value:
                try:
                    idx = int(value)
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"Índice de freeze inválido: {value}") from exc
                if 0 <= idx < total:
                    indices.append(idx)
            return sorted(set(indices))

        raise TypeError(f"Formato de freeze no soportado: {type(freeze_value)!r}")


    def _apply_freeze(self, model, freeze_value: Union[int, List[int], str, None]) -> None:
        indices = self._resolve_freeze_indices(model, freeze_value)
        if not indices:
            return

        modules = list(model.model.model)  # type: ignore[attr-defined]
        for idx in indices:
            module = modules[idx]
            for param in module.parameters():
                param.requires_grad = False
                
    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"No se encontró el archivo de configuración: {path}")
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
                
    def _build_config(self) -> Dict[str, Any]:
        config_path = self._data_path
        base_config = self._load_yaml(config_path)

        cli_overrides: Dict[str, Any] = {
            "data": base_config,
            "model": "yolo11n.pt",
            "epochs": 50,
            "imgsz": 320,
            "batch": 1,
            "project": "runs",
            "name": "finetune",
            "device": "null",
            "workers": 0,
            "lr0": 0.01,
            "lrf": 0.01,
            "momentum": 0.937,
            "weight_decay": 0.0005,
            "patience": 30,
            "augment": True,
            "freeze": "backbone",
        }

        # Elimina claves con None para no sobrescribir valores del YAML.
        filtered_overrides = {k: v for k, v in cli_overrides.items() if v is not None}
        base_config.update(filtered_overrides)
        return base_config
                
    def train(self):
        if not self._freeze_applied:
            self._apply_freeze(self._model, self._freezed_value)
            
        self._model.train(**self._training_config)
        
    def load_state_dict(self, params):
        self._model.model.load_state_dict(params)        
        
    def get_model_parameters(self):
        return self._model.model.state_dict()
    
    def get_model_weight(self):
        #TODO ver cuantos samples hay en el dataset
        pass

