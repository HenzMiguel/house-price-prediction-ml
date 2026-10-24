"""Static evaluation and Optuna plots stored as immutable artifacts."""

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from optuna.importance import get_param_importances  # noqa: E402


def _save(figure: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    figure.savefig(path, dpi=120, metadata={"Software": "house-price-mlops"})
    plt.close(figure)
    return path


def evaluation_plots(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    output_dir: Path,
    *,
    feature_names: tuple[str, ...],
    estimator: Any,
) -> list[Path]:
    residuals = y_true - y_pred
    outputs: list[Path] = []

    figure, axis = plt.subplots()
    axis.scatter(y_true, y_pred, alpha=0.25, s=8)
    limits = [float(min(y_true.min(), y_pred.min())), float(max(y_true.max(), y_pred.max()))]
    axis.plot(limits, limits, "r--")
    axis.set(xlabel="Observed", ylabel="Predicted", title="Predicted vs observed")
    outputs.append(_save(figure, output_dir / "predicted_actual.png"))

    figure, axis = plt.subplots()
    axis.scatter(y_pred, residuals, alpha=0.25, s=8)
    axis.axhline(0, color="red", linestyle="--")
    axis.set(xlabel="Predicted", ylabel="Residual", title="Residuals")
    outputs.append(_save(figure, output_dir / "residuals.png"))

    figure, axis = plt.subplots()
    axis.hist(residuals, bins=40)
    axis.set(xlabel="Residual", ylabel="Count", title="Error distribution")
    outputs.append(_save(figure, output_dir / "error_distribution.png"))

    importance = getattr(estimator, "feature_importances_", None)
    if importance is None:
        importance = getattr(estimator, "coef_", None)
    if importance is not None and len(np.ravel(importance)) == len(feature_names):
        figure, axis = plt.subplots(figsize=(8, 4))
        axis.bar(feature_names, np.ravel(importance))
        axis.tick_params(axis="x", rotation=35)
        axis.set(title="Feature importance / coefficients")
        outputs.append(_save(figure, output_dir / "feature_importance.png"))
    return outputs


def optimization_history(study: Any, output_dir: Path) -> Path:
    complete = [trial for trial in study.trials if trial.value is not None]
    numbers = [trial.number for trial in complete]
    values = [trial.value for trial in complete]
    best = np.minimum.accumulate(values) if values else []
    figure, axis = plt.subplots()
    axis.plot(numbers, values, "o", label="trial RMSE")
    axis.plot(numbers, best, label="best so far")
    axis.set(xlabel="Trial", ylabel="CV RMSE", title="Optimization history")
    axis.legend()
    return _save(figure, output_dir / "optimization_history.png")


def parameter_importance(study: Any, output_dir: Path) -> Path:
    """Render a stable artifact even when too few trials exist for importance."""
    try:
        importances = get_param_importances(study)
    except (RuntimeError, ValueError, ZeroDivisionError):
        importances = {}
    figure, axis = plt.subplots()
    if importances:
        names = list(importances)
        axis.bar(names, [importances[name] for name in names])
        axis.tick_params(axis="x", rotation=35)
        axis.set(ylabel="Importance", title="Hyperparameter importance")
    else:
        axis.text(0.5, 0.5, "Insufficient completed trials", ha="center", va="center")
        axis.set_axis_off()
    return _save(figure, output_dir / "parameter_importance.png")
