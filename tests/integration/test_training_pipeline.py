from pathlib import Path

from house_price.data.validation import load_and_validate_snapshot
from house_price.domain import CandidateFamily
from house_price.training.dataset import build_estimator, deterministic_split
from house_price.training.evaluation import regression_metrics


def test_five_families_share_one_holdout_and_emit_four_metrics(
    dataset_paths: tuple[Path, Path],
) -> None:
    frame, _ = load_and_validate_snapshot(*dataset_paths)
    split = deterministic_split(frame.head(1_000))
    parameters = {
        CandidateFamily.LINEAR: {},
        CandidateFamily.RIDGE: {"alpha": 1.0},
        CandidateFamily.LASSO: {"alpha": 0.001},
        CandidateFamily.DECISION_TREE: {"max_depth": 5},
        CandidateFamily.RANDOM_FOREST: {"n_estimators": 10, "max_depth": 5},
    }
    results = {}
    for family in CandidateFamily:
        model = build_estimator(family, parameters[family])
        model.fit(split.x_train, split.y_train)
        results[family] = regression_metrics(split.y_test, model.predict(split.x_test))
    assert set(results) == set(CandidateFamily)
    assert all(
        set(metrics.__dict__) == {"mae", "mse", "rmse", "r2"}
        for metrics in results.values()
    )

