from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, Optional


class MetricLoader:
    """Thread-safe container to store and query the latest trainer metrics."""

    def __init__(self) -> None:
        self._phase_metrics: Dict[str, Dict[str, Any]] = {}
        self._confusion_matrices: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()

    def record_metrics(self, phase: str, metrics: Dict[str, Any], step: Optional[int] = None) -> None:
        """Persist a batch of metrics associated with a training phase."""
        if not metrics:
            return

        normalized = {
            self._normalize_metric_name(phase, name): self._to_python(value) for name, value in metrics.items()
        }
        with self._lock:
            payload = self._phase_metrics.setdefault(
                phase,
                {
                    "metrics": {},
                    "step": None,
                    "updated_at": None,
                },
            )
            payload["metrics"].update(normalized)
            if step is not None:
                payload["step"] = step
            payload["updated_at"] = datetime.now(timezone.utc)

    def record_metric(self, phase: str, metric_name: str, value: Any, step: Optional[int] = None) -> None:
        """Convenience wrapper to store a single metric."""
        self.record_metrics(phase, {metric_name: value}, step=step)

    def record_confusion_matrix(
        self,
        phase: str,
        matrix: Any,
        *,
        labels: Optional[Any] = None,
        step: Optional[int] = None,
    ) -> None:
        """Store the most recent confusion matrix for a phase."""
        if matrix is None:
            return

        serialized = self._to_python(matrix)
        with self._lock:
            self._confusion_matrices[phase] = {
                "matrix": serialized,
                "labels": self._to_python(labels) if labels is not None else None,
                "step": step,
                "updated_at": datetime.now(timezone.utc),
            }

    def get_phase_metrics(self, phase: str) -> Optional[Dict[str, Any]]:
        """Return a copy of the metrics recorded for a given phase."""
        with self._lock:
            entry = self._phase_metrics.get(phase)
            return deepcopy(entry)

    def get_metric(self, phase: str, metric_name: str) -> Optional[Any]:
        """Return a specific metric for a phase if available."""
        with self._lock:
            entry = self._phase_metrics.get(phase)
            if not entry:
                return None
            return deepcopy(entry["metrics"].get(metric_name))

    def get_all_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Return a copy of every stored metric grouped by phase."""
        with self._lock:
            return deepcopy(self._phase_metrics)

    def get_confusion_matrix(self, phase: str) -> Optional[Dict[str, Any]]:
        """Return the latest recorded confusion matrix for a phase."""
        with self._lock:
            entry = self._confusion_matrices.get(phase)
            return deepcopy(entry)

    @staticmethod
    def _normalize_metric_name(phase: str, metric_name: str) -> str:
        """Strip duplicated phase prefixes from metric names."""
        if "/" in metric_name:
            prefix, value = metric_name.split("/", 1)
            if prefix.strip() == phase.strip():
                return value
        return metric_name

    @staticmethod
    def _to_python(value: Any) -> Any:
        """Convert tensors or numpy types to plain Python structures."""
        if value is None:
            return None
        attr_detach = getattr(value, "detach", None)
        if callable(attr_detach):
            value = attr_detach()
        attr_cpu = getattr(value, "cpu", None)
        if callable(attr_cpu):
            value = attr_cpu()
        attr_item = getattr(value, "item", None)
        if callable(attr_item):
            try:
                return attr_item()
            except Exception:
                pass
        attr_tolist = getattr(value, "tolist", None)
        if callable(attr_tolist):
            try:
                return attr_tolist()
            except Exception:
                pass
        return value
