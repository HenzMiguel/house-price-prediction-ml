"""Regression metrics, quality gates, and deterministic winner selection."""

import math
from collections.abc import Iterable
from dataclasses import replace

import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from house_price.domain import FAMILY_ORDER, ModelCandidate, ModelMetrics


def regression_metrics(y_true: Iterable[float], y_pred: Iterable[float]) -> ModelMetrics:
    truth = np.asarray(list(y_true), dtype=float)
    prediction = np.asarray(list(y_pred), dtype=float)
    mse = float(mean_squared_error(truth, prediction))
    metrics = ModelMetrics(
        mae=float(mean_absolute_error(truth, prediction)),
        mse=mse,
        rmse=float(math.sqrt(mse)),
        r2=float(r2_score(truth, prediction)),
    )
    if not all(math.isfinite(x) for x in metrics.__dict__.values()):
        raise ValueError("evaluation produced non-finite metrics")
    return metrics


def relative_increase(new: float, previous: float) -> float:
    if previous < 0 or new < 0:
        raise ValueError("error metrics cannot be negative")
    if previous == 0:
        return 0.0 if new == 0 else math.inf
    return (new - previous) / previous


def evaluate_gate(
    metrics: ModelMetrics, champion: ModelMetrics | None, *, max_relative_increase: float = 0.05
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not all(math.isfinite(value) for value in metrics.__dict__.values()):
        reasons.append("non_finite_metrics")
    if metrics.r2 < 0.50:
        reasons.append("r2_below_0_50")
    if champion is not None:
        mae_increase = relative_increase(metrics.mae, champion.mae)
        rmse_increase = relative_increase(metrics.rmse, champion.rmse)
        if mae_increase > max_relative_increase and not math.isclose(
            mae_increase, max_relative_increase, rel_tol=0, abs_tol=1e-12
        ):
            reasons.append("mae_regression_above_5_percent")
        if rmse_increase > max_relative_increase and not math.isclose(
            rmse_increase, max_relative_increase, rel_tol=0, abs_tol=1e-12
        ):
            reasons.append("rmse_regression_above_5_percent")
    return not reasons, reasons


def apply_gate(candidate: ModelCandidate, champion: ModelMetrics | None) -> ModelCandidate:
    eligible, reasons = evaluate_gate(candidate.metrics, champion)
    return replace(candidate, eligible=eligible, ineligibility_reasons=reasons)


def select_winner(candidates: Iterable[ModelCandidate]) -> ModelCandidate | None:
    family_rank = {family: index for index, family in enumerate(FAMILY_ORDER)}
    eligible = [candidate for candidate in candidates if candidate.eligible]
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda candidate: (
            candidate.metrics.rmse,
            candidate.metrics.mae,
            -candidate.metrics.r2,
            family_rank[candidate.family],
        ),
    )
