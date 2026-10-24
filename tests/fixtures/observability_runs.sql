-- Five deterministic executions and five candidates per execution for Grafana acceptance tests.
INSERT INTO observability.training_runs
  (training_run_id, mlflow_parent_run_id, dataset_version, dataset_checksum, code_revision,
   started_at, completed_at, status, failure_stage, promoted_model_version, updated_at)
SELECT
  ('00000000-0000-4000-8000-' || lpad(run_number::text, 12, '0'))::uuid,
  'fixture-parent-' || run_number,
  'fixture-dataset-v1', repeat('a', 64), 'fixture-revision',
  timestamptz '2026-10-20 12:00:00+00' + (run_number || ' hours')::interval,
  timestamptz '2026-10-20 12:10:00+00' + (run_number || ' hours')::interval,
  CASE WHEN run_number = 4 THEN 'failed'
       WHEN run_number = 5 THEN 'succeeded_no_promotion' ELSE 'succeeded' END,
  CASE WHEN run_number = 4 THEN 'optimizing' END,
  CASE WHEN run_number IN (1,2,3) THEN 'fixture-v' || run_number END,
  timestamptz '2026-10-20 12:10:00+00' + (run_number || ' hours')::interval
FROM generate_series(1, 5) AS run_number;

INSERT INTO observability.model_metrics
  (training_run_id, candidate_family, mlflow_run_id, best_trial_number, mae, mse, rmse, r2,
   eligible, promoted, ineligibility_reasons, measured_at, artifact_uri)
SELECT
  ('00000000-0000-4000-8000-' || lpad(run_number::text, 12, '0'))::uuid,
  family,
  'fixture-' || run_number || '-' || family,
  0,
  0.45 + family_number * 0.01 + run_number * 0.001,
  power(0.65 + family_number * 0.01 + run_number * 0.001, 2),
  0.65 + family_number * 0.01 + run_number * 0.001,
  0.70 - family_number * 0.01,
  run_number <> 5,
  run_number IN (1,2,3) AND family_number = 1,
  CASE WHEN run_number = 5 THEN '["quality_gate"]'::jsonb ELSE '[]'::jsonb END,
  timestamptz '2026-10-20 12:09:00+00' + (run_number || ' hours')::interval,
  'runs:/fixture-' || run_number || '-' || family || '/model'
FROM generate_series(1, 5) AS run_number
CROSS JOIN unnest(ARRAY['linear','ridge','lasso','decision_tree','random_forest'])
  WITH ORDINALITY AS families(family, family_number);

INSERT INTO observability.inference_metrics
  (window_started_at, window_seconds, environment_version, model_version, health_status,
   request_count, error_count, latency_p50_ms, latency_p95_ms, latency_p99_ms,
   latency_max_ms, recorded_at)
SELECT
  timestamptz '2026-10-20 13:00:00+00' + (minute || ' minutes')::interval,
  60, 'fixture-environment-v1', 'fixture-v3',
  CASE WHEN minute = 4 THEN 'unavailable' ELSE 'ready' END,
  10, CASE WHEN minute = 4 THEN 10 ELSE 0 END,
  10, 20, 30, 40,
  timestamptz '2026-10-20 13:00:30+00' + (minute || ' minutes')::interval
FROM generate_series(0, 4) AS minute;

