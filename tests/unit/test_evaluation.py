from uuid import uuid4

import numpy as np

from house_price.domain import CandidateFamily, ModelCandidate, ModelMetrics
from house_price.training.dataset import deterministic_split, training_folds
from house_price.training.evaluation import (
    apply_gate,
    regression_metrics,
    relative_increase,
    select_winner,
)


def candidate(family: CandidateFamily, rmse: float, mae: float, r2: float) -> ModelCandidate:
    return ModelCandidate(
        training_run_id=str(uuid4()),
        family=family,
        mlflow_run_id=str(uuid4()),
        best_trial_number=0,
        parameters={},
        metrics=ModelMetrics(mae=mae, mse=rmse**2, rmse=rmse, r2=r2),
        eligible=True,
    )


def test_metrics_use_truth_then_prediction() -> None:
    metrics = regression_metrics([1.0, 2.0, 3.0], [1.0, 2.0, 4.0])
    assert np.isclose(metrics.mae, 1 / 3)
    assert np.isclose(metrics.mse, 1 / 3)
    assert np.isclose(metrics.rmse, np.sqrt(1 / 3))
    assert np.isclose(metrics.r2, 0.5)


def test_first_promotion_only_requires_absolute_r2_gate() -> None:
    accepted = apply_gate(candidate(CandidateFamily.LINEAR, 10, 10, 0.5), None)
    rejected = apply_gate(candidate(CandidateFamily.LINEAR, 0.1, 0.1, 0.49), None)
    assert accepted.eligible
    assert rejected.ineligibility_reasons == ["r2_below_0_50"]


def test_relative_gates_and_zero_baseline() -> None:
    champion = ModelMetrics(mae=1.0, mse=1.0, rmse=1.0, r2=0.8)
    assert apply_gate(candidate(CandidateFamily.RIDGE, 1.05, 1.05, 0.8), champion).eligible
    assert not apply_gate(candidate(CandidateFamily.RIDGE, 1.051, 1.0, 0.8), champion).eligible
    assert relative_increase(0, 0) == 0
    assert np.isinf(relative_increase(0.01, 0))


def test_winner_tie_breaking_is_deterministic() -> None:
    candidates = [
        candidate(CandidateFamily.RANDOM_FOREST, 1.0, 0.9, 0.8),
        candidate(CandidateFamily.RIDGE, 1.0, 0.8, 0.7),
        candidate(CandidateFamily.LASSO, 1.0, 0.8, 0.9),
        candidate(CandidateFamily.LINEAR, 1.0, 0.8, 0.9),
    ]
    assert select_winner(candidates).family == CandidateFamily.LINEAR


def test_split_and_folds_are_reproducible(dataset_paths) -> None:
    from house_price.data.validation import load_and_validate_snapshot

    frame, _ = load_and_validate_snapshot(*dataset_paths)
    first = deterministic_split(frame)
    second = deterministic_split(frame)
    assert first.x_train.index.tolist() == second.x_train.index.tolist()
    assert not set(first.x_train.index) & set(first.x_test.index)
    folds = list(training_folds().split(first.x_train))
    assert len(folds) == 5

