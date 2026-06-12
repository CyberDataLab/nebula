import logging
import math

import numpy as np
import shap
import torch
from scipy.spatial.distance import jensenshannon
from scipy.stats import entropy, variation

logger = logging.getLogger(__name__)


def _feature_importance_cv_from_values(vals):
    # Higher CV means attributions differ more across features, i.e. a more selective explanation.
    vals = np.asarray(vals, dtype=float).reshape(-1)
    vals = np.nan_to_num(vals, nan=0.0, posinf=0.0, neginf=0.0)
    vals = vals[vals > 0]

    if len(vals) <= 1:
        return 0.0

    cv = float(variation(vals))
    if math.isnan(cv) or math.isinf(cv):
        return 1.0
    return max(0.0, cv)


def _get_feature_importances(model, test_sample):
    # Computes global feature importances with a simple modality-aware policy:
    # SHAP for tabular tensors and Integrated Gradients for image-like tensors.
    if not isinstance(model, torch.nn.Module):
        logger.warning("Model is not a torch.nn.Module")
        return np.array([])

    if not isinstance(test_sample, (tuple, list)) or len(test_sample) < 1:
        return np.array([])

    inputs = test_sample[0]
    if not torch.is_tensor(inputs) or inputs.ndim < 2 or inputs.size(0) == 0:
        return np.array([])

    try:
        device = next(model.parameters()).device
    except Exception:
        device = torch.device("cpu")

    inputs = inputs.to(device)
    if not torch.is_floating_point(inputs):
        inputs = inputs.float()

    was_training = bool(getattr(model, "training", False))
    model.eval()

    try:
        if inputs.ndim == 2:
            logger.info("Computing tabular feature importances with SHAP, input_shape=%s", tuple(inputs.shape))
            importances = _get_shap_importances(model, inputs)
        else:
            logger.info("Computing image-like feature importances with Integrated Gradients, input_shape=%s", tuple(inputs.shape))
            importances = _get_integrated_gradients_importances(model, inputs)

        logger.info("Computed feature importances, n_features=%s, total_importance=%s", len(importances), float(np.sum(importances)))
        return importances
    except Exception as exc:
        logger.warning("Could not compute feature importances")
        logger.warning(exc)
        return np.array([])
    finally:
        if was_training:
            model.train()


def _get_shap_importances(model, inputs):
    # SHAP is a natural fit for tabular data: one attribution per input column.
    if inputs.size(0) < 2:
        return np.array([])

    background_size = min(16, inputs.size(0) - 1)
    background = inputs[:background_size]
    explained = inputs[background_size:]

    logger.info("SHAP background_size=%s, explained_size=%s", int(background.size(0)), int(explained.size(0)))
    explainer = shap.GradientExplainer(model, background)
    shap_values = explainer.shap_values(explained)

    if isinstance(shap_values, (list, tuple)):
        arrays = [np.asarray(values, dtype=float) for values in shap_values if values is not None]
        if not arrays:
            return np.array([])
        shap_arr = np.stack(arrays, axis=0)
        importances = np.mean(np.abs(shap_arr), axis=(0, 1))
    else:
        shap_arr = np.asarray(shap_values, dtype=float)
        if shap_arr.ndim == 3:
            importances = np.mean(np.abs(shap_arr), axis=(0, 2))
        else:
            importances = np.mean(np.abs(shap_arr), axis=0)

    return _clean_importances(importances)


def _get_integrated_gradients_importances(model, inputs, steps=16):
    # Zero baseline is simple and works well for normalized image tensors.
    logger.info("Integrated Gradients steps=%s", int(steps))
    baseline = torch.zeros_like(inputs)
    total_gradients = torch.zeros_like(inputs)

    for alpha in torch.linspace(0.0, 1.0, steps, device=inputs.device):
        scaled_inputs = (baseline + alpha * (inputs - baseline)).detach().requires_grad_(True)
        model.zero_grad(set_to_none=True)

        outputs = model(scaled_inputs)
        if isinstance(outputs, (tuple, list)):
            outputs = outputs[0]

        # Explain the model's predicted class for each sample.
        if outputs.ndim == 1:
            score = outputs.sum()
        else:
            score = outputs.reshape(outputs.shape[0], -1).max(dim=1).values.sum()

        gradients = torch.autograd.grad(score, scaled_inputs)[0]
        total_gradients += gradients.detach()

    attributions = (inputs - baseline) * total_gradients / float(steps)
    importances = torch.abs(attributions).mean(dim=0)

    if importances.ndim == 3:
        # For RGB images, keep one importance value per spatial position.
        importances = importances.mean(dim=0)

    return _clean_importances(importances.detach().cpu().numpy())


def _clean_importances(importances):
    importances = np.asarray(importances, dtype=float).reshape(-1)
    importances = np.nan_to_num(importances, nan=0.0, posinf=0.0, neginf=0.0)
    return np.maximum(importances, 0.0)


def _alpha_score_from_values(vals, alpha=0.8):
    # Fraction of features needed to explain alpha of the attribution mass; lower is better.
    vals = np.asarray(vals, dtype=float).reshape(-1)
    vals = np.nan_to_num(vals, nan=0.0, posinf=0.0, neginf=0.0)
    vals = np.maximum(vals, 0.0)
    total_features = len(vals)
    if total_features == 0 or np.sum(vals) <= 1e-12:
        return 1.0

    try:
        alpha = float(alpha)
    except Exception:
        alpha = 0.8
    alpha = min(max(alpha, 0.0), 1.0)

    vals_sorted = np.sort(vals)[::-1]
    cum_sum = np.cumsum(vals_sorted)
    threshold = float(alpha) * np.sum(vals_sorted)
    idx = np.searchsorted(cum_sum, threshold)
    return float(min(total_features, idx + 1) / total_features)


def _spread_base_from_values(vals, divergence=True):
    # Entropy ratio measures spread; JS divergence measures distance from uniform attribution.
    vals = np.asarray(vals, dtype=float).reshape(-1)
    tol = 1e-8

    if len(vals) == 0 or np.sum(vals) < tol:
        return 0.0 if divergence else 1.0
    if len(vals) == 1:
        return 0.0 if divergence else 1.0

    weights = vals / np.sum(vals)
    equal_weights = np.ones(len(vals)) / len(vals)

    if divergence:
        metric = jensenshannon(weights, equal_weights, base=2)
    else:
        denom = entropy(equal_weights)
        metric = 0.0 if denom <= tol else entropy(weights) / denom

    if math.isnan(metric) or math.isinf(metric):
        return 0.0 if divergence else 1.0
    return float(np.clip(metric, 0.0, 1.0))


def get_explainability_metrics_summary(model, test_dataloader, max_batches=4):
    # Computes explainability metrics over multiple test batches and returns their mean values.
    summary = {
        "feature_importance_cv": 1.0,
        "alpha_score": 1.0,
        "spread_ratio": 1.0,
        "spread_divergence": 0.0,
    }

    if test_dataloader is None:
        return summary

    try:
        max_batches = max(1, int(max_batches))
    except Exception:
        max_batches = 4

    fi_values = []
    alpha_values = []
    spread_ratio_values = []
    spread_divergence_values = []

    try:
        for batch_idx, test_sample in enumerate(test_dataloader):
            if batch_idx >= max_batches:
                break

            # Compute attributions once per batch and derive all explainability metrics from them.
            importances = _get_feature_importances(model, test_sample)
            fi_values.append(float(_feature_importance_cv_from_values(importances)))
            alpha_values.append(float(_alpha_score_from_values(importances)))
            spread_ratio_values.append(float(_spread_base_from_values(importances, divergence=False)))
            spread_divergence_values.append(float(_spread_base_from_values(importances, divergence=True)))
    except Exception as exc:
        logger.warning("Could not compute explainability metrics summary")
        logger.warning(exc)

    if fi_values:
        summary["feature_importance_cv"] = float(np.mean(fi_values))
    if alpha_values:
        summary["alpha_score"] = float(np.mean(alpha_values))
    if spread_ratio_values:
        summary["spread_ratio"] = float(np.mean(spread_ratio_values))
    if spread_divergence_values:
        summary["spread_divergence"] = float(np.mean(spread_divergence_values))

    return summary
