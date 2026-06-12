# nebula/addons/trustworthiness/per_round_metrics.py
from __future__ import annotations

import asyncio
import csv
import os
from dataclasses import dataclass, field
from typing import Optional


from nebula.addons.functions import print_msg_box


def _safe_get_round(engine) -> int:
    trainer = getattr(engine, "trainer", None)
    if trainer is None:
        return -1

    try:
        return int(trainer.get_round())
    except Exception:
        return int(getattr(trainer, "round", -1))


@dataclass
class PerRoundTrustMetrics:
    experiment_name: str
    participant_idx: int
    trust_dir: str
    role_label: str

    enable_print: bool = True
    enable_csv: bool = True

    _csv_path: str = field(init=False)
    _prev_acc: Optional[float] = field(default=None, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def setup(self, engine) -> None:
        os.makedirs(self.trust_dir, exist_ok=True)
        self._csv_path = os.path.join(
            self.trust_dir, f"round_metrics_participant_{self.participant_idx}.csv"
        )

        if self.enable_csv and not os.path.exists(self._csv_path):
            with open(self._csv_path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow([
                    "round",
                    "participant",
                    "role",
                    "loss",
                    "accuracy",
                    "tw_stability",
                ])
    async def on_test_metrics(self, engine, loss: float, acc: float) -> None:
        async with self._lock:
            round_id = _safe_get_round(engine)

            if self._prev_acc is None:
                tw_stability = 1.0
            else:
                tw_stability = 1.0 - abs(acc - self._prev_acc)
                tw_stability = max(0.0, min(1.0, tw_stability))
            self._prev_acc = acc

            if self.enable_csv:
                with open(self._csv_path, "a", newline="") as f:
                    w = csv.writer(f)
                    w.writerow([
                        round_id,
                        self.participant_idx,
                        self.role_label,
                        float(loss),
                        float(acc),
                        float(tw_stability),
                    ])

            if self.enable_print:
                print_msg_box(
                    msg=(
                        f"Round: {round_id}\n"
                        f"Loss: {loss:.4f}\n"
                        f"Accuracy: {acc:.4f}\n"
                        f"TW/Stability: {tw_stability:.4f}\n"
                    ),
                    indent=2,
                    title=f"Trustworthiness (per-round) | {self.role_label} | Participant: {self.participant_idx}",
                )
