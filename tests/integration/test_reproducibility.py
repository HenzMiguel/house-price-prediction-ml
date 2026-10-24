import numpy as np

from house_price.data.validation import load_and_validate_snapshot
from house_price.domain import CandidateFamily
from house_price.training.dataset import build_estimator, deterministic_split
from house_price.training.evaluation import regression_metrics


def test_five_repetitions_produce_equal_metrics_and_decision(dataset_paths) -> None:
    frame, snapshot = load_and_validate_snapshot(*dataset_paths)
    outcomes = []
    for _ in range(5):
        split = deterministic_split(frame.head(2_000), seed=42)
        model = build_estimator(CandidateFamily.RIDGE, {"alpha": 1.0}, seed=42)
        model.fit(split.x_train, split.y_train)
        metrics = regression_metrics(split.y_test, model.predict(split.x_test))
        outcomes.append((snapshot.sha256, metrics, metrics.r2 >= 0.50))
    first = outcomes[0]
    for outcome in outcomes[1:]:
        assert outcome[0] == first[0]
        assert outcome[2] == first[2]
        assert np.allclose(
            list(outcome[1].__dict__.values()),
            list(first[1].__dict__.values()),
            rtol=0,
            atol=1e-9,
        )

