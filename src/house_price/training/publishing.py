"""Transactional publication of training projections."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from house_price.domain import ModelCandidate, TrainingStatus
from house_price.tracking.observability import ObservabilityRepository


class ProjectionError(RuntimeError):
    pass


class TrainingPublisher:
    def __init__(self, repository: ObservabilityRepository) -> None:
        self.repository = repository

    def publish_run(self, **values: object) -> None:
        try:
            self.repository.upsert_training_run(values)
        except Exception as exc:
            raise ProjectionError("failed to publish training run") from exc

    def publish_candidate(self, candidate: ModelCandidate) -> None:
        values = {
            "training_run_id": candidate.training_run_id,
            "candidate_family": candidate.family.value,
            "mlflow_run_id": candidate.mlflow_run_id,
            "best_trial_number": candidate.best_trial_number,
            **candidate.metrics.__dict__,
            "eligible": candidate.eligible,
            "promoted": candidate.promoted,
            "ineligibility_reasons": json.dumps(candidate.ineligibility_reasons),
            "measured_at": candidate.measured_at or datetime.now(UTC),
            "artifact_uri": candidate.artifact_uri,
        }
        try:
            self.repository.upsert_model_metric(values)
        except Exception as exc:
            raise ProjectionError("failed to publish model candidate") from exc

    def publish_trial(
        self,
        *,
        training_run_id: str,
        candidate_family: str,
        study_name: str,
        trial: Any,
        mlflow_run_id: str,
    ) -> None:
        state_name = trial.state.name.lower()
        if state_name == "fail":
            state_name = "failed"
        duration = getattr(trial, "duration", None)
        values = {
            "study_name": study_name,
            "trial_number": trial.number,
            "training_run_id": training_run_id,
            "candidate_family": candidate_family,
            "mlflow_run_id": mlflow_run_id,
            "objective_rmse": getattr(trial, "value", None),
            "state": state_name,
            "duration_seconds": duration.total_seconds() if duration else None,
            "parameters_json": json.dumps(trial.params, sort_keys=True),
            "completed_at": getattr(trial, "datetime_complete", None),
        }
        try:
            self.repository.upsert_optimization_trial(values)
        except Exception as exc:
            raise ProjectionError("failed to publish optimization trial") from exc

    def publish_plot(
        self,
        *,
        training_run_id: str,
        candidate_family: str,
        mlflow_run_id: str,
        plot: Path,
    ) -> None:
        plot_type = plot.stem
        identity = f"{training_run_id}:{candidate_family}:{plot_type}"
        values = {
            "plot_id": str(uuid5(NAMESPACE_URL, identity)),
            "training_run_id": training_run_id,
            "mlflow_run_id": mlflow_run_id,
            "candidate_family": candidate_family,
            "plot_type": plot_type,
            "artifact_uri": f"runs:/{mlflow_run_id}/plots/{plot.name}",
            "created_at": datetime.now(UTC),
        }
        try:
            self.repository.upsert_artifact_plot(values)
        except Exception as exc:
            raise ProjectionError("failed to publish artifact plot") from exc

    def publish_failure(self, run_values: dict[str, object], stage: str) -> None:
        self.publish_run(
            **{
                **run_values,
                "status": TrainingStatus.FAILED.value,
                "failure_stage": stage,
                "completed_at": datetime.now(UTC),
            }
        )
