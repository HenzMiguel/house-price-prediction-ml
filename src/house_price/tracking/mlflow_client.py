"""Narrow MLflow integration used by training and promotion."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import mlflow
from mlflow import MlflowClient

REGISTERED_MODEL_NAME = "house-price-regressor"
CHAMPION_ALIAS = "champion"
EXPERIMENT_NAME = "house-price-training"


class TrackingClient:
    def __init__(self, tracking_uri: str, experiment_name: str = EXPERIMENT_NAME) -> None:
        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(experiment_name)
        self.client = MlflowClient(tracking_uri=tracking_uri)

    @contextmanager
    def run(self, *, run_name: str, tags: dict[str, str], nested: bool = False) -> Iterator[Any]:
        with mlflow.start_run(run_name=run_name, nested=nested, tags=tags) as active:
            yield active

    @staticmethod
    def log_parameters(parameters: dict[str, Any]) -> None:
        mlflow.log_params(parameters)

    @staticmethod
    def log_metrics(metrics: dict[str, float]) -> None:
        mlflow.log_metrics(metrics)

    @staticmethod
    def log_artifact(path: str, artifact_path: str | None = None) -> None:
        mlflow.log_artifact(path, artifact_path=artifact_path)

    def ensure_registered_model(self) -> None:
        try:
            self.client.get_registered_model(REGISTERED_MODEL_NAME)
        except Exception:
            self.client.create_registered_model(REGISTERED_MODEL_NAME)

    def register_without_alias(self, model_uri: str, run_id: str) -> str:
        self.ensure_registered_model()
        version = mlflow.register_model(model_uri, REGISTERED_MODEL_NAME)
        self.client.set_model_version_tag(
            REGISTERED_MODEL_NAME, version.version, "source_run_id", run_id
        )
        return str(version.version)

    def get_champion_version(self) -> str | None:
        try:
            return str(
                self.client.get_model_version_by_alias(
                    REGISTERED_MODEL_NAME, CHAMPION_ALIAS
                ).version
            )
        except Exception:
            return None

    def set_champion(self, version: str) -> None:
        self.client.set_registered_model_alias(REGISTERED_MODEL_NAME, CHAMPION_ALIAS, version)

    def restore_champion(self, version: str | None) -> None:
        if version is None:
            try:
                self.client.delete_registered_model_alias(REGISTERED_MODEL_NAME, CHAMPION_ALIAS)
            except Exception:
                pass
        else:
            self.set_champion(version)
