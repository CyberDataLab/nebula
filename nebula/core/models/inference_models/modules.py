"""Custom modules required by the YOLO dual-head workflow."""

from __future__ import annotations

from typing import Iterable

import torch
import torch.nn as nn


class ConcatHead(nn.Module):
    """Concatenate predictions coming from two Detect heads."""

    def __init__(self, nc1: int = 80, nc2: int = 1, ch: Iterable[int] | tuple[int, ...] = ()):  # pylint: disable=unused-argument
        super().__init__()
        self.nc1 = nc1
        self.nc2 = nc2

    def forward(self, x):  # type: ignore[override]
        """Merge bounding boxes and class scores from two detection heads."""

        if isinstance(x[0], tuple):
            preds1, preds2 = x[0][0], x[1][0]
        elif isinstance(x[0], list):
            return [torch.cat((x0, x1), dim=1) for x0, x1 in zip(x[0], x[1])]
        else:
            preds1, preds2 = x[0], x[1]

        concatenated = torch.cat((preds1[:, :4, :], preds2[:, :4, :]), dim=2)

        def extend(preds, pad_left: bool) -> torch.Tensor:
            shape = list(preds.shape)
            shape[-1] = preds1.shape[-1] + preds2.shape[-1]
            extended = torch.zeros(shape, device=preds.device, dtype=preds.dtype)
            if pad_left:
                extended[..., preds.shape[-1] :] = preds
            else:
                extended[..., : preds.shape[-1]] = preds
            return extended

        preds1_extended = extend(preds1, pad_left=False)
        preds2_extended = extend(preds2, pad_left=True)
        concatenated = torch.cat((concatenated, preds1_extended[:, 4:, :]), dim=1)
        concatenated = torch.cat((concatenated, preds2_extended[:, 4:, :]), dim=1)

        if isinstance(x[0], tuple):
            return concatenated, x[0][1]
        return concatenated
