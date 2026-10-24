"""Idempotent SQL projection for the stable observability contract."""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import Engine, create_engine, text


class ObservabilityRepository:
    def __init__(self, database_url: str | None = None, *, engine: Engine | None = None) -> None:
        if engine is None and database_url is None:
            raise ValueError("database_url or engine is required")
        self.engine = engine or create_engine(database_url, pool_pre_ping=True)

    def execute(self, statement: str, values: Mapping[str, Any]) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(statement), values)

    def upsert_training_run(self, values: Mapping[str, Any]) -> None:
        self.execute(
            """
            INSERT INTO observability.training_runs
              (training_run_id, mlflow_parent_run_id, dataset_version, dataset_checksum,
               code_revision, started_at, completed_at, status, failure_stage,
               promoted_model_version, updated_at)
            VALUES
              (:training_run_id, :mlflow_parent_run_id, :dataset_version, :dataset_checksum,
               :code_revision, :started_at, :completed_at, :status, :failure_stage,
               :promoted_model_version, now())
            ON CONFLICT (training_run_id) DO UPDATE SET
              completed_at=EXCLUDED.completed_at, status=EXCLUDED.status,
              failure_stage=EXCLUDED.failure_stage,
              promoted_model_version=EXCLUDED.promoted_model_version, updated_at=now()
            """,
            values,
        )

    def upsert_model_metric(self, values: Mapping[str, Any]) -> None:
        self.execute(
            """
            INSERT INTO observability.model_metrics
              (training_run_id, candidate_family, mlflow_run_id, best_trial_number,
               mae, mse, rmse, r2, eligible, promoted, ineligibility_reasons,
               measured_at, artifact_uri)
            VALUES
              (:training_run_id, :candidate_family, :mlflow_run_id, :best_trial_number,
               :mae, :mse, :rmse, :r2, :eligible, :promoted,
               CAST(:ineligibility_reasons AS jsonb), :measured_at, :artifact_uri)
            ON CONFLICT (training_run_id, candidate_family) DO UPDATE SET
              mae=EXCLUDED.mae, mse=EXCLUDED.mse, rmse=EXCLUDED.rmse, r2=EXCLUDED.r2,
              eligible=EXCLUDED.eligible, promoted=EXCLUDED.promoted,
              ineligibility_reasons=EXCLUDED.ineligibility_reasons,
              measured_at=EXCLUDED.measured_at, artifact_uri=EXCLUDED.artifact_uri
            """,
            values,
        )

    def upsert_optimization_trial(self, values: Mapping[str, Any]) -> None:
        self.execute(
            """
            INSERT INTO observability.optimization_trials
              (study_name, trial_number, training_run_id, candidate_family,
               mlflow_run_id, objective_rmse, state, duration_seconds,
               parameters_json, completed_at)
            VALUES
              (:study_name, :trial_number, :training_run_id, :candidate_family,
               :mlflow_run_id, :objective_rmse, :state, :duration_seconds,
               CAST(:parameters_json AS jsonb), :completed_at)
            ON CONFLICT (study_name, trial_number) DO UPDATE SET
              mlflow_run_id=EXCLUDED.mlflow_run_id,
              objective_rmse=EXCLUDED.objective_rmse, state=EXCLUDED.state,
              duration_seconds=EXCLUDED.duration_seconds,
              parameters_json=EXCLUDED.parameters_json,
              completed_at=EXCLUDED.completed_at
            """,
            values,
        )

    def upsert_artifact_plot(self, values: Mapping[str, Any]) -> None:
        self.execute(
            """
            INSERT INTO observability.artifact_plots
              (plot_id, training_run_id, mlflow_run_id, candidate_family,
               plot_type, artifact_uri, created_at)
            VALUES
              (:plot_id, :training_run_id, :mlflow_run_id, :candidate_family,
               :plot_type, :artifact_uri, :created_at)
            ON CONFLICT (plot_id) DO UPDATE SET
              mlflow_run_id=EXCLUDED.mlflow_run_id,
              artifact_uri=EXCLUDED.artifact_uri,
              created_at=EXCLUDED.created_at
            """,
            values,
        )

    def upsert_inference_metric(self, values: Mapping[str, Any]) -> None:
        self.execute(
            """
            INSERT INTO observability.inference_metrics
              (window_started_at, window_seconds, environment_version, model_version,
               health_status, request_count, error_count, latency_p50_ms,
               latency_p95_ms, latency_p99_ms, latency_max_ms, recorded_at)
            VALUES
              (:window_started_at, :window_seconds, :environment_version, :model_version,
               :health_status, :request_count, :error_count, :latency_p50_ms,
               :latency_p95_ms, :latency_p99_ms, :latency_max_ms, :recorded_at)
            ON CONFLICT (window_started_at, environment_version, model_version) DO UPDATE SET
              health_status=EXCLUDED.health_status, request_count=EXCLUDED.request_count,
              error_count=EXCLUDED.error_count, latency_p50_ms=EXCLUDED.latency_p50_ms,
              latency_p95_ms=EXCLUDED.latency_p95_ms, latency_p99_ms=EXCLUDED.latency_p99_ms,
              latency_max_ms=EXCLUDED.latency_max_ms, recorded_at=EXCLUDED.recorded_at
            """,
            values,
        )
