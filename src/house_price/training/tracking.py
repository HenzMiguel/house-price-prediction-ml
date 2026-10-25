"""MLflow hierarchy for pipeline, family, trial, and finalist artifacts."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import mlflow
import mlflow.sklearn

from house_price.domain import ModelMetrics
from house_price.tracking.mlflow_client import TrackingClient


class TrainingTracker:
    def __init__(self, client: TrackingClient) -> None:
        self.client = client

    @contextmanager
    def parent_run(self, run_id: str, tags: dict[str, str]) -> Iterator[str]:
        with self.client.run(run_name=f"training-{run_id}", tags=tags) as active:
            yield active.info.run_id

    @contextmanager
    def family_run(self, family: str, tags: dict[str, str]) -> Iterator[str]:
        with self.client.run(run_name=family, tags=tags, nested=True) as active:
            yield active.info.run_id

    @contextmanager
    def trial_run(self, family: str, number: int, parameters: dict[str, Any]) -> Iterator[str]:
        with self.client.run(
            run_name=f"{family}-trial-{number}",
            tags={"candidate_family": family, "trial_number": str(number)},
            nested=True,
        ) as active:
            mlflow.log_params(parameters)
            yield active.info.run_id

    @staticmethod
    def log_finalist(
        estimator: Any,
        metrics: ModelMetrics,
        parameters: dict[str, Any],
        plots: list[Path],
        *,
        input_example: Any,
    ) -> None:
        mlflow.log_params(parameters)
        mlflow.log_metrics(metrics.__dict__)
        for plot in plots:
            mlflow.log_artifact(str(plot), artifact_path="plots")
        with TemporaryDirectory(prefix="mlflow-model-") as temporary:
            model_path = Path(temporary) / "model"
            mlflow.sklearn.save_model(
                estimator,
                path=str(model_path),
                input_example=input_example,
                serialization_format="cloudpickle",
            )
            mlflow.log_artifacts(str(model_path), artifact_path="model")
