import logging
import math
import numbers
from math import e

import numpy as np
import torch
from sklearn.metrics import roc_auc_score, roc_curve
from torch import nn

logger = logging.getLogger(__name__)

def get_global_privacy_risk(dp, epsilon, n):
    # Calculates the global privacy risk by epsilon and the number of clients.

    try:
        epsilon = float(epsilon)
        n = float(n)
    except (TypeError, ValueError):
        return 1

    if dp is True and isinstance(epsilon, numbers.Number):
        return 1 / (1 + (n - 1) * math.pow(e, -epsilon))
    else:
        return 1


def get_global_privacy_risk_dfl(dp, epsilon, n):
    # Calculates the global privacy risk by epsilon and the number of clients for DFL.

    try:
        epsilon = float(epsilon)
        n = float(n)
    except (TypeError, ValueError):
        return 1

    if dp is True and isinstance(epsilon, numbers.Number):
        return 1 / (1 + (n + 1) * math.pow(e, -epsilon))
    else:
        return 1


def _collect_per_sample_losses(model, dataloader, max_samples=5000):
    # Compute per-sample cross-entropy losses for a dataloader.
    if not isinstance(model, torch.nn.Module) or dataloader is None:
        return np.array([])

    try:
        device = next(model.parameters()).device
    except Exception:
        device = torch.device("cpu")

    criterion = nn.CrossEntropyLoss(reduction="none")
    losses = []
    collected = 0

    model.eval()
    with torch.no_grad():
        for batch in dataloader:
            if not isinstance(batch, (tuple, list)) or len(batch) < 2:
                continue

            samples, labels = batch[0], batch[1]
            if not torch.is_tensor(samples) or not torch.is_tensor(labels):
                continue

            remaining = max_samples - collected
            if remaining <= 0:
                break

            samples = samples[:remaining].to(device)
            labels = labels[:remaining]

            if labels.ndim > 1:
                labels = torch.argmax(labels, dim=1)

            labels = labels.long().to(device)

            outputs = model(samples)
            logits = outputs[0] if isinstance(outputs, (tuple, list)) else outputs
            batch_losses = criterion(logits, labels)

            batch_losses_np = batch_losses.detach().cpu().numpy()
            batch_losses_np = batch_losses_np[np.isfinite(batch_losses_np)]
            if batch_losses_np.size == 0:
                continue

            losses.append(batch_losses_np)
            collected += int(batch_losses.shape[0])

    if not losses:
        return np.array([])

    return np.concatenate(losses, axis=0)


def get_epsilon_star(model, train_dataloader, test_dataloader, max_samples=5000, percentile=95):
    # Compute empirical epsilon* from train/test loss distributions.
    try:
        loss_train = _collect_per_sample_losses(model, train_dataloader, max_samples=max_samples)
        loss_test = _collect_per_sample_losses(model, test_dataloader, max_samples=max_samples)

        if loss_train.size == 0 or loss_test.size == 0:
            return 0.0

        scores = np.concatenate([-loss_train, -loss_test])
        y_true = np.concatenate([np.ones(len(loss_train)), np.zeros(len(loss_test))])

        fpr, tpr, _ = roc_curve(y_true, scores)

        fpr_floor = 1.0 / len(loss_test)
        fnr_floor = 1.0 / len(loss_train)

        fpr = np.clip(fpr, fpr_floor, 1 - fpr_floor)
        fnr = np.clip(1 - tpr, fnr_floor, 1 - fnr_floor)

        delta = 1.0 / len(loss_train) if len(loss_train) > 0 else 1e-5

        m1 = (1 - delta - fnr) / fpr
        m2 = (1 - delta - fpr) / fnr
        m3 = (fnr - delta) / (1 - fpr)
        m4 = (fpr - delta) / (1 - fnr)

        ratios = np.maximum.reduce([m1, m2, m3, m4, np.ones_like(m1)])
        ratios = ratios[np.isfinite(ratios)]
        if ratios.size == 0:
            return 0.0

        epsilon_star_val = np.log(np.nanpercentile(ratios, percentile))

        if np.isnan(epsilon_star_val) or np.isinf(epsilon_star_val):
            return 0.0

        return float(max(0.0, epsilon_star_val))
    except Exception as exc:
        logger.warning("Could not compute epsilon_star")
        logger.warning(exc)
        return 0.0


def get_mia_auc(model, train_dataloader, test_dataloader, max_samples=5000):
    # Compute membership inference attack AUC using per-sample loss as the attack score.
    try:
        loss_train = _collect_per_sample_losses(model, train_dataloader, max_samples=max_samples)
        loss_test = _collect_per_sample_losses(model, test_dataloader, max_samples=max_samples)

        if loss_train.size == 0 or loss_test.size == 0:
            return 0.5

        scores = np.concatenate([-loss_train, -loss_test])
        y_true = np.concatenate([np.ones(len(loss_train)), np.zeros(len(loss_test))])
        mia_auc = roc_auc_score(y_true, scores)

        if np.isnan(mia_auc) or np.isinf(mia_auc):
            return 0.5

        return float(np.clip(mia_auc, 0.0, 1.0))
    except Exception as exc:
        logger.warning("Could not compute mia_auc")
        logger.warning(exc)
        return 0.5
