"""
Runtime modifications applied to the Ultralytics package so that the dual-head
workflow can run without cloning or patching the repository on disk.
"""

from __future__ import annotations

import contextlib
import inspect
import logging
from typing import Any, Dict, Iterable

import torch
import torch.nn as nn
from ultralytics.nn import modules as modules_init
from ultralytics.nn.modules import conv as conv_module
from ultralytics.nn import tasks as tasks_module
from ultralytics.utils import LOGGER as ULTRA_LOGGER, colorstr
from ultralytics.utils.ops import make_divisible


logger = logging.getLogger(__name__)


def ensure_ultralytics_multihead_support() -> None:
    """
    Patch the in-memory Ultralytics modules so they understand the ConcatHead layer and
    can handle multiple Detect heads, mirroring the git patch used in the reference Colab.
    """

    if getattr(tasks_module, "_yolo_def_patched", False):  # type: ignore[attr-defined]
        return

    # ------------------------------------------------------------------ #
    # ConcatHead definition
    # ------------------------------------------------------------------ #

    try:
        ConcatHead = conv_module.ConcatHead  # type: ignore[attr-defined]
    except AttributeError:

        from modules import ConcatHead

        conv_module.ConcatHead = ConcatHead  # type: ignore[attr-defined]
        if hasattr(conv_module, "__all__") and "ConcatHead" not in conv_module.__all__:
            conv_module.__all__ = tuple(list(conv_module.__all__) + ["ConcatHead"])  # type: ignore[attr-defined]
    else:
        ConcatHead = conv_module.ConcatHead  # type: ignore[attr-defined]

    modules_init.ConcatHead = ConcatHead  # type: ignore[attr-defined]
    if hasattr(modules_init, "__all__") and "ConcatHead" not in modules_init.__all__:
        modules_init.__all__ = tuple(list(modules_init.__all__) + ["ConcatHead"])  # type: ignore[attr-defined]
    tasks_module.ConcatHead = ConcatHead  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ #
    # BaseModel._apply patch
    # ------------------------------------------------------------------ #

    BaseModel = tasks_module.BaseModel
    if not getattr(BaseModel._apply, "_yolo_def_patched", False):
        original_apply = BaseModel._apply

        def _apply_multi(self, fn):  # type: ignore[override]
            self = original_apply(self, fn)
            model_ref = getattr(self, "model", [])
            for module in model_ref:
                if isinstance(module, tasks_module.Detect):
                    module.stride = fn(module.stride)
                    module.anchors = fn(module.anchors)
                    module.strides = fn(module.strides)
            return self

        _apply_multi._yolo_def_patched = True  # type: ignore[attr-defined]
        BaseModel._apply = _apply_multi  # type: ignore[assignment]

    # ------------------------------------------------------------------ #
    # DetectionModel.__init__ patch
    # ------------------------------------------------------------------ #

    DetectionModel = tasks_module.DetectionModel
    detection_src = inspect.getsource(DetectionModel.__init__)
    if "detect_modules =" not in detection_src:
        original_init = DetectionModel.__init__

        def _init_multi(self, cfg="yolo11n.yaml", ch=3, nc=None, verbose=True):  # type: ignore[override]
            original_init(self, cfg, ch, nc, verbose)
            detect_modules = [module for module in self.model if isinstance(module, tasks_module.Detect)]
            if not detect_modules:
                return

            s = 256
            primary = detect_modules[-1]
            for module in detect_modules:
                module.inplace = self.inplace

            def _forward(x):
                if self.end2end:
                    return self.forward(x)["one2many"]
                return self.forward(x)[0] if isinstance(
                    primary, (tasks_module.Segment, tasks_module.YOLOESegment, tasks_module.Pose, tasks_module.OBB)
                ) else self.forward(x)

            self.model.eval()
            for module in detect_modules:
                module.training = True
            stride = torch.tensor([s / x.shape[-2] for x in _forward(torch.zeros(1, ch, s, s))])
            self.stride = stride
            for module in detect_modules:
                module.stride = stride
                module.bias_init()
            self.model.train()

        DetectionModel.__init__ = _init_multi  # type: ignore[assignment]

    # ------------------------------------------------------------------ #
    # parse_model replacement
    # ------------------------------------------------------------------ #

    parse_src = inspect.getsource(tasks_module.parse_model)
    if "ConcatHead" not in parse_src:
        original_parse = tasks_module.parse_model

        def parse_model_patched(model_dict: Dict[str, Any], ch: int, verbose: bool = True):
            """
            Replica of Ultralytics' :func:`parse_model` with ConcatHead support added and the stride-handling logic
            aligned to the dual-head workflow.
            """

            import ast

            legacy = True
            max_channels = float("inf")
            nc, act, scales = (model_dict.get(x) for x in ("nc", "activation", "scales"))
            depth, width, _ = (model_dict.get(x, 1.0) for x in ("depth_multiple", "width_multiple", "kpt_shape"))
            scale = model_dict.get("scale")
            if scales:
                if not scale:
                    scale = tuple(scales.keys())[0]
                    ULTRA_LOGGER.warning(f"no model scale passed. Assuming scale='{scale}'.")
                depth, width, max_channels = scales[scale]

            if act:
                tasks_module.Conv.default_act = eval(act)  # type: ignore[assignment]
                if verbose:
                    ULTRA_LOGGER.info(f"{colorstr('activation:')} {act}")

            if verbose:
                ULTRA_LOGGER.info(f"\n{'':>3}{'from':>20}{'n':>3}{'params':>10}  {'module':<45}{'arguments':<30}")

            channels = [ch]
            layers, save, c2 = [], [], channels[-1]
            base_modules = frozenset(
                {
                    tasks_module.Classify,
                    tasks_module.Conv,
                    tasks_module.ConvTranspose,
                    tasks_module.GhostConv,
                    tasks_module.Bottleneck,
                    tasks_module.GhostBottleneck,
                    tasks_module.SPP,
                    tasks_module.SPPF,
                    tasks_module.C2fPSA,
                    tasks_module.C2PSA,
                    tasks_module.DWConv,
                    tasks_module.Focus,
                    tasks_module.BottleneckCSP,
                    tasks_module.C1,
                    tasks_module.C2,
                    tasks_module.C2f,
                    tasks_module.C3k2,
                    tasks_module.RepNCSPELAN4,
                    tasks_module.ELAN1,
                    tasks_module.ADown,
                    tasks_module.AConv,
                    tasks_module.SPPELAN,
                    tasks_module.C2fAttn,
                    tasks_module.C3,
                    tasks_module.C3TR,
                    tasks_module.C3Ghost,
                    torch.nn.ConvTranspose2d,
                    tasks_module.DWConvTranspose2d,
                    tasks_module.C3x,
                    tasks_module.RepC3,
                    tasks_module.PSA,
                    tasks_module.SCDown,
                    tasks_module.C2fCIB,
                    tasks_module.A2C2f,
                }
            )
            repeat_modules = frozenset(
                {
                    tasks_module.BottleneckCSP,
                    tasks_module.C1,
                    tasks_module.C2,
                    tasks_module.C2f,
                    tasks_module.C3k2,
                    tasks_module.C2fAttn,
                    tasks_module.C3,
                    tasks_module.C3TR,
                    tasks_module.C3Ghost,
                    tasks_module.C3x,
                    tasks_module.RepC3,
                    tasks_module.C2fPSA,
                    tasks_module.C2fCIB,
                    tasks_module.C2PSA,
                    tasks_module.A2C2f,
                }
            )

            for i, (f, n, m, args) in enumerate(model_dict["backbone"] + model_dict["head"]):
                module_cls = (
                    getattr(torch.nn, m[3:])
                    if "nn." in m
                    else getattr(__import__("torchvision").ops, m[16:])
                    if "torchvision.ops." in m
                    else tasks_module.__dict__[m]
                )
                for j, a in enumerate(args):
                    if isinstance(a, str):
                        with contextlib.suppress(ValueError):
                            args[j] = locals()[a] if a in locals() else ast.literal_eval(a)
                repeats = max(round(n * depth), 1) if n > 1 else n
                repeats_original = repeats

                if module_cls in base_modules:
                    c1, c2 = channels[f], args[0]
                    if c2 != nc:
                        c2 = make_divisible(min(c2, max_channels) * width, 8)
                    if module_cls is tasks_module.C2fAttn:
                        args[1] = make_divisible(min(args[1], max_channels // 2) * width, 8)
                        args[2] = int(
                            max(
                                round(min(args[2], max_channels // 2 // 32)) * width,
                                1,
                            )
                            if args[2] > 1
                            else args[2]
                        )

                    args = [c1, c2, *args[1:]]
                    if module_cls in repeat_modules:
                        args.insert(2, repeats)
                        repeats = 1
                    if module_cls is tasks_module.C3k2:
                        legacy = False
                        if scale in "mlx":
                            args[3] = True
                    if module_cls is tasks_module.A2C2f:
                        legacy = False
                        if scale in "lx":
                            args.extend((True, 1.2))
                    if module_cls is tasks_module.C2fCIB:
                        legacy = False
                elif module_cls is tasks_module.AIFI:
                    args = [channels[f], *args]
                elif module_cls in frozenset({tasks_module.HGStem, tasks_module.HGBlock}):
                    c1, cm, c2 = channels[f], args[0], args[1]
                    args = [c1, cm, c2, *args[2:]]
                    if module_cls is tasks_module.HGBlock:
                        args.insert(4, repeats)
                        repeats = 1
                elif module_cls is tasks_module.ResNetLayer:
                    c2 = args[1] if args[3] else args[1] * 4
                elif module_cls is torch.nn.BatchNorm2d:
                    args = [channels[f]]
                elif module_cls is tasks_module.Concat:
                    c2 = sum(channels[x] for x in f)
                elif module_cls in frozenset(
                    {
                        tasks_module.ConcatHead,
                        tasks_module.Detect,
                        tasks_module.WorldDetect,
                        tasks_module.YOLOEDetect,
                        tasks_module.Segment,
                        tasks_module.YOLOESegment,
                        tasks_module.Pose,
                        tasks_module.OBB,
                        tasks_module.ImagePoolingAttn,
                        tasks_module.v10Detect,
                    }
                ):
                    args.append([channels[x] for x in f])
                    if module_cls is tasks_module.Segment or module_cls is tasks_module.YOLOESegment:
                        args[2] = make_divisible(min(args[2], max_channels) * width, 8)
                    if module_cls in {
                        tasks_module.Detect,
                        tasks_module.YOLOEDetect,
                        tasks_module.Segment,
                        tasks_module.YOLOESegment,
                        tasks_module.Pose,
                        tasks_module.OBB,
                    }:
                        module_cls.legacy = legacy  # type: ignore[attr-defined]
                elif module_cls is tasks_module.RTDETRDecoder:
                    args.insert(1, [channels[x] for x in f])
                elif module_cls is tasks_module.CBLinear:
                    c2 = args[0]
                    c1 = channels[f]
                    args = [c1, c2, *args[1:]]
                elif module_cls is tasks_module.CBFuse:
                    c2 = channels[f[-1]]
                elif module_cls in frozenset({tasks_module.TorchVision, tasks_module.Index}):
                    c2 = args[0]
                    _ = channels[f]
                    args = [*args[1:]]
                else:
                    c2 = channels[f]

                module = (
                    torch.nn.Sequential(*(module_cls(*args) for _ in range(repeats)))
                    if repeats > 1
                    else module_cls(*args)
                )
                module_type = str(module_cls)[8:-2].replace("__main__.", "")
                module.np = sum(x.numel() for x in module.parameters())  # type: ignore[attr-defined]
                module.i, module.f, module.type = i, f, module_type  # type: ignore[attr-defined]
                if verbose:
                    ULTRA_LOGGER.info(
                        f"{i:>3}{str(f):>20}{repeats_original:>3}{module.np:10.0f}  {module_type:<45}{str(args):<30}"
                    )
                save.extend(x % i for x in ([f] if isinstance(f, int) else f) if x != -1)
                layers.append(module)
                if i == 0:
                    channels = []
                channels.append(c2)

            return torch.nn.Sequential(*layers), sorted(save)

        tasks_module.parse_model = parse_model_patched  # type: ignore[assignment]

    tasks_module._yolo_def_patched = True  # type: ignore[attr-defined]
    logger.debug("Ultralytics runtime successfully patched for dual-head workflow.")
