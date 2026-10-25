"""Create the durable model catalog ledger."""

# ruff: noqa: E501 -- SQL contract lines are intentionally kept intact.

from alembic import op

revision = "003_model_catalog"
down_revision = "002_grafana_views"
branch_labels = None
depends_on = None

UP_SQL = r"""
REVOKE ALL ON SCHEMA catalog FROM PUBLIC;
GRANT USAGE ON SCHEMA catalog TO pipeline_writer;

CREATE TABLE catalog.model_entries (
  model_version text PRIMARY KEY CHECK (model_version ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
  manifest_schema_version text NOT NULL CHECK (manifest_schema_version IN ('1.0.0','2.0.0')),
  manifest_sha256 char(64) NOT NULL CHECK (manifest_sha256 ~ '^[a-f0-9]{64}$'),
  model_sha256 char(64) NOT NULL CHECK (model_sha256 ~ '^[a-f0-9]{64}$'),
  package_relpath text NOT NULL UNIQUE CHECK (package_relpath ~ '^models/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
  training_run_id uuid NOT NULL,
  source_mlflow_run_id text,
  source_mlflow_model_version text,
  active_mlflow_run_id text,
  active_mlflow_model_version text,
  registered_model_name text NOT NULL DEFAULT 'house-price-regressor'
    CHECK (registered_model_name = 'house-price-regressor'),
  integrity_status text NOT NULL CHECK (integrity_status IN
    ('unknown','verifying','verified','invalid','missing','unsupported')),
  catalog_status text NOT NULL CHECK (catalog_status IN
    ('unregistered','registering','registered','registration_failed','conflict')),
  lifecycle_status text NOT NULL CHECK (lifecycle_status IN
    ('active','quarantined','deletion_requested','trashed','deleted')),
  promotion_status text NOT NULL CHECK (promotion_status IN
    ('candidate','champion','superseded','rejected')),
  diagnostic_code text CHECK (diagnostic_code ~ '^[a-z][a-z0-9_]{0,63}$'),
  first_seen_at timestamptz NOT NULL,
  verified_at timestamptz,
  last_reconciled_at timestamptz,
  revision integer NOT NULL DEFAULT 1 CHECK (revision >= 1),
  CHECK (active_mlflow_model_version IS NULL OR catalog_status = 'registered'),
  CHECK (promotion_status <> 'champion' OR
    (integrity_status = 'verified' AND catalog_status = 'registered' AND lifecycle_status = 'active'))
);
CREATE UNIQUE INDEX catalog_one_active_mlflow_version
  ON catalog.model_entries(active_mlflow_model_version)
  WHERE active_mlflow_model_version IS NOT NULL;
CREATE UNIQUE INDEX catalog_one_champion
  ON catalog.model_entries((promotion_status)) WHERE promotion_status = 'champion';

CREATE TABLE catalog.reconciliation_runs (
  reconciliation_id uuid PRIMARY KEY,
  trigger text NOT NULL CHECK (trigger IN ('manual','startup','weekly','restore')),
  mode text NOT NULL CHECK (mode IN ('check','apply')),
  scan_fingerprint char(64) NOT NULL CHECK (scan_fingerprint ~ '^[a-f0-9]{64}$'),
  status text NOT NULL CHECK (status IN
    ('running','succeeded','partial','failed','lock_unavailable')),
  started_at timestamptz NOT NULL,
  completed_at timestamptz,
  scanned_count integer NOT NULL DEFAULT 0 CHECK (scanned_count >= 0),
  registered_count integer NOT NULL DEFAULT 0 CHECK (registered_count BETWEEN 0 AND scanned_count),
  recovered_count integer NOT NULL DEFAULT 0 CHECK (recovered_count BETWEEN 0 AND scanned_count),
  quarantined_count integer NOT NULL DEFAULT 0 CHECK (quarantined_count BETWEEN 0 AND scanned_count),
  unchanged_count integer NOT NULL DEFAULT 0 CHECK (unchanged_count BETWEEN 0 AND scanned_count),
  mlflow_evidence_run_id text,
  CHECK (completed_at IS NULL OR completed_at >= started_at)
);

CREATE TABLE catalog.reconciliation_items (
  reconciliation_id uuid NOT NULL REFERENCES catalog.reconciliation_runs(reconciliation_id),
  package_relpath text NOT NULL CHECK (package_relpath ~ '^models/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
  model_version text,
  manifest_sha256 char(64) CHECK (manifest_sha256 ~ '^[a-f0-9]{64}$'),
  action text NOT NULL CHECK (action IN
    ('verified','registered','recovered','quarantined','unchanged','conflict')),
  result text NOT NULL CHECK (result IN ('succeeded','failed','skipped')),
  reason_code text CHECK (reason_code ~ '^[a-z][a-z0-9_]{0,63}$'),
  mlflow_run_id text,
  mlflow_model_version text,
  occurred_at timestamptz NOT NULL,
  PRIMARY KEY (reconciliation_id, package_relpath)
);

CREATE TABLE catalog.operation_events (
  event_id uuid PRIMARY KEY,
  operation_id uuid NOT NULL,
  operation text NOT NULL CHECK (operation IN
    ('publish','reconcile','resolve_champion','delete','purge')),
  model_version text,
  from_state jsonb,
  to_state jsonb,
  phase text NOT NULL,
  result text NOT NULL CHECK (result IN ('started','succeeded','failed','compensated')),
  reason_code text CHECK (reason_code ~ '^[a-z][a-z0-9_]{0,63}$'),
  occurred_at timestamptz NOT NULL
);

CREATE TABLE catalog.deletion_requests (
  deletion_id uuid PRIMARY KEY,
  model_version text NOT NULL,
  requested_at timestamptz NOT NULL,
  confirmed_at timestamptz,
  state text NOT NULL CHECK (state IN
    ('planned','confirmed','trashed','purged','refused','failed')),
  package_relpath text NOT NULL CHECK (package_relpath ~ '^models/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
  trash_relpath text,
  impact jsonb NOT NULL,
  reason_code text,
  CHECK (state NOT IN ('refused','failed') OR reason_code IS NOT NULL)
);
CREATE UNIQUE INDEX catalog_one_active_deletion
  ON catalog.deletion_requests(model_version)
  WHERE state IN ('planned','confirmed','trashed');

CREATE FUNCTION catalog.reject_event_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'catalog.operation_events is append-only';
END $$;
CREATE TRIGGER operation_events_append_only
  BEFORE UPDATE OR DELETE ON catalog.operation_events
  FOR EACH ROW EXECUTE FUNCTION catalog.reject_event_mutation();

GRANT SELECT, INSERT, UPDATE ON catalog.model_entries,
  catalog.reconciliation_runs, catalog.reconciliation_items,
  catalog.deletion_requests TO pipeline_writer;
GRANT SELECT, INSERT ON catalog.operation_events TO pipeline_writer;
"""


def upgrade() -> None:
    op.execute(UP_SQL)


def downgrade() -> None:
    op.execute(DOWN_SQL)


DOWN_SQL = (
    "DROP TABLE IF EXISTS catalog.deletion_requests, catalog.operation_events, "
    "catalog.reconciliation_items, catalog.reconciliation_runs, "
    "catalog.model_entries CASCADE; DROP FUNCTION IF EXISTS catalog.reject_event_mutation();"
)
