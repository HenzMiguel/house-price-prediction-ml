"""Create stable observability tables."""

from alembic import op

revision = "001_observability_tables"
down_revision = None
branch_labels = None
depends_on = None

UP_SQL = r"""
CREATE TABLE observability.training_runs (
  training_run_id uuid PRIMARY KEY,
  mlflow_parent_run_id text NOT NULL UNIQUE,
  dataset_version text NOT NULL,
  dataset_checksum char(64) NOT NULL CHECK (dataset_checksum ~ '^[a-f0-9]{64}$'),
  code_revision text NOT NULL,
  started_at timestamptz NOT NULL,
  completed_at timestamptz,
  status text NOT NULL CHECK (status IN ('pending','validating','optimizing','evaluating',
    'publishing_metrics','promoting','succeeded','succeeded_no_promotion',
    'skipped_concurrent','failed')),
  failure_stage text,
  promoted_model_version text,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (completed_at IS NULL OR completed_at >= started_at),
  CHECK (status <> 'failed' OR failure_stage IS NOT NULL)
);

CREATE TABLE observability.model_metrics (
  training_run_id uuid NOT NULL REFERENCES observability.training_runs(training_run_id),
  candidate_family text NOT NULL CHECK (candidate_family IN
    ('linear','ridge','lasso','decision_tree','random_forest')),
  mlflow_run_id text NOT NULL UNIQUE,
  best_trial_number integer NOT NULL CHECK (best_trial_number >= 0),
  mae double precision NOT NULL CHECK (mae NOT IN ('NaN','Infinity','-Infinity') AND mae >= 0),
  mse double precision NOT NULL CHECK (mse NOT IN ('NaN','Infinity','-Infinity') AND mse >= 0),
  rmse double precision NOT NULL CHECK (rmse NOT IN ('NaN','Infinity','-Infinity') AND rmse >= 0),
  r2 double precision NOT NULL CHECK (r2 NOT IN ('NaN','Infinity','-Infinity')),
  eligible boolean NOT NULL,
  promoted boolean NOT NULL DEFAULT false,
  ineligibility_reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
  measured_at timestamptz NOT NULL,
  artifact_uri text NOT NULL,
  PRIMARY KEY (training_run_id, candidate_family),
  CHECK (jsonb_typeof(ineligibility_reasons) = 'array'),
  CHECK (NOT eligible OR ineligibility_reasons = '[]'::jsonb)
);
CREATE UNIQUE INDEX one_promoted_model_per_run
  ON observability.model_metrics(training_run_id) WHERE promoted;
CREATE INDEX model_metrics_measured_at ON observability.model_metrics(measured_at);
CREATE INDEX model_metrics_family ON observability.model_metrics(candidate_family);

CREATE TABLE observability.optimization_trials (
  study_name text NOT NULL,
  trial_number integer NOT NULL CHECK (trial_number >= 0),
  training_run_id uuid NOT NULL REFERENCES observability.training_runs(training_run_id),
  candidate_family text NOT NULL CHECK (candidate_family IN
    ('linear','ridge','lasso','decision_tree','random_forest')),
  mlflow_run_id text NOT NULL UNIQUE,
  objective_rmse double precision CHECK (
    objective_rmse IS NULL OR objective_rmse NOT IN ('NaN','Infinity','-Infinity')),
  state text NOT NULL CHECK (state IN ('running','complete','pruned','failed')),
  duration_seconds double precision CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
  parameters_json jsonb NOT NULL,
  completed_at timestamptz,
  PRIMARY KEY (study_name, trial_number)
);
CREATE INDEX optimization_trial_run_family
  ON observability.optimization_trials(training_run_id, candidate_family);

CREATE TABLE observability.artifact_plots (
  plot_id uuid PRIMARY KEY,
  training_run_id uuid NOT NULL REFERENCES observability.training_runs(training_run_id),
  mlflow_run_id text NOT NULL,
  candidate_family text,
  plot_type text NOT NULL CHECK (plot_type IN ('predicted_actual','residuals',
    'error_distribution','feature_importance','optimization_history','parameter_importance')),
  artifact_uri text NOT NULL,
  created_at timestamptz NOT NULL
);

CREATE TABLE observability.inference_metrics (
  window_started_at timestamptz NOT NULL,
  window_seconds integer NOT NULL DEFAULT 60 CHECK (window_seconds > 0),
  environment_version text NOT NULL,
  model_version text NOT NULL,
  health_status text NOT NULL CHECK (health_status IN ('ready','degraded','unavailable')),
  request_count bigint NOT NULL CHECK (request_count >= 0),
  error_count bigint NOT NULL CHECK (error_count BETWEEN 0 AND request_count),
  latency_p50_ms double precision,
  latency_p95_ms double precision,
  latency_p99_ms double precision,
  latency_max_ms double precision,
  recorded_at timestamptz NOT NULL,
  PRIMARY KEY (window_started_at, environment_version, model_version),
  CHECK ((request_count = 0 AND latency_p50_ms IS NULL AND latency_p95_ms IS NULL
    AND latency_p99_ms IS NULL AND latency_max_ms IS NULL) OR
    (request_count > 0 AND latency_p50_ms >= 0 AND latency_p95_ms >= latency_p50_ms
    AND latency_p99_ms >= latency_p95_ms AND latency_max_ms >= latency_p99_ms))
);

GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA observability TO pipeline_writer;
REVOKE ALL ON ALL TABLES IN SCHEMA observability FROM grafana_reader;
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS observability.inference_metrics, "
        "observability.artifact_plots, observability.optimization_trials, "
        "observability.model_metrics, observability.training_runs CASCADE"
    )
