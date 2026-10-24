"""Create stable read-only Grafana views."""

from alembic import op

revision = "002_grafana_views"
down_revision = "001_observability_tables"
branch_labels = None
depends_on = None

VIEW_NAMES = (
    "grafana_model_metric_history",
    "grafana_candidate_comparison",
    "grafana_training_status",
    "grafana_optuna_convergence",
    "grafana_inference_operations",
)

UP_SQL = r"""
CREATE OR REPLACE VIEW observability.grafana_model_metric_history AS
SELECT m.measured_at, m.training_run_id, m.candidate_family, m.mae, m.mse, m.rmse,
       m.r2, m.eligible, m.promoted, r.dataset_version,
       CASE WHEN m.promoted THEN r.promoted_model_version END AS model_version
FROM observability.model_metrics m
JOIN observability.training_runs r USING (training_run_id);

CREATE OR REPLACE VIEW observability.grafana_candidate_comparison AS
SELECT training_run_id, candidate_family, mae, mse, rmse, r2, eligible, promoted,
       ineligibility_reasons, artifact_uri
FROM observability.model_metrics;

CREATE OR REPLACE VIEW observability.grafana_training_status AS
SELECT started_at, completed_at,
       EXTRACT(epoch FROM completed_at - started_at) AS duration_seconds,
       training_run_id, status, failure_stage, dataset_version, promoted_model_version,
       EXTRACT(epoch FROM now() - max(completed_at) OVER ()) AS metric_age_seconds
FROM observability.training_runs;

CREATE OR REPLACE VIEW observability.grafana_optuna_convergence AS
SELECT completed_at, training_run_id, candidate_family, study_name, trial_number,
       objective_rmse,
       min(objective_rmse) OVER (
         PARTITION BY study_name ORDER BY trial_number ROWS UNBOUNDED PRECEDING
       ) AS best_so_far_rmse,
       duration_seconds, state
FROM observability.optimization_trials;

CREATE OR REPLACE VIEW observability.grafana_inference_operations AS
SELECT window_started_at, environment_version, model_version, health_status,
       request_count, error_count,
       CASE WHEN request_count = 0 THEN 0 ELSE error_count::double precision / request_count END
         AS error_rate,
       latency_p50_ms, latency_p95_ms, latency_p99_ms, latency_max_ms,
       EXTRACT(epoch FROM now() - recorded_at) AS heartbeat_age_seconds
FROM observability.inference_metrics;

REVOKE ALL ON ALL TABLES IN SCHEMA observability FROM grafana_reader;
GRANT SELECT ON observability.grafana_model_metric_history,
  observability.grafana_candidate_comparison,
  observability.grafana_training_status,
  observability.grafana_optuna_convergence,
  observability.grafana_inference_operations TO grafana_reader;
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    for name in reversed(VIEW_NAMES):
        op.execute(f"DROP VIEW IF EXISTS observability.{name}")
