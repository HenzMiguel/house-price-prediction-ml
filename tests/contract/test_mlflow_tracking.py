from pathlib import Path

import mlflow

from house_price.tracking.mlflow_client import TrackingClient
from house_price.training.tracking import TrainingTracker


def test_parent_family_trial_hierarchy_and_tags(tmp_path: Path) -> None:
    uri = f"sqlite:///{tmp_path / 'mlflow.db'}"
    client = TrackingClient(uri, "contract-test")
    tracker = TrainingTracker(client)
    with tracker.parent_run("run-1", {"dataset_checksum": "a" * 64}) as parent:
        with tracker.family_run("ridge", {"candidate_family": "ridge"}) as family:
            with tracker.trial_run("ridge", 0, {"alpha": 1.0}) as trial:
                mlflow.log_metric("cv_rmse_mean", 1.0)
    raw_family = client.client.get_run(family)
    raw_trial = client.client.get_run(trial)
    assert raw_family.data.tags["mlflow.parentRunId"] == parent
    assert raw_trial.data.tags["mlflow.parentRunId"] == family
    assert raw_trial.data.params["alpha"] == "1.0"

