"""Transactional PostgreSQL ledger accessed independently of MLflow internals."""

import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, create_engine, text

from house_price.catalog import CatalogLockUnavailable, CatalogPersistenceError
from house_price.catalog.models import (
    DeletionRequest,
    ModelEntry,
    OperationEvent,
    ReconciliationRun,
)

DEFAULT_ADVISORY_LOCK_ID = 0x485052494345


def _parameters(record: Any) -> dict[str, Any]:
    values = record.model_dump(mode="python")
    for key, value in tuple(values.items()):
        if hasattr(value, "value"):
            values[key] = value.value
        elif isinstance(value, UUID):
            values[key] = str(value)
        elif isinstance(value, dict):
            values[key] = json.dumps(value, sort_keys=True)
    return values


class CatalogRepository:
    def __init__(
        self,
        database_url: str | None = None,
        *,
        engine: Engine | None = None,
        advisory_lock_id: int = DEFAULT_ADVISORY_LOCK_ID,
    ) -> None:
        if engine is None and database_url is None:
            raise ValueError("database_url or engine is required")
        self.engine = engine or create_engine(database_url, pool_pre_ping=True)
        self.advisory_lock_id = advisory_lock_id

    @contextmanager
    def mutation_lock(self) -> Iterator[Connection]:
        with self.engine.connect() as connection:
            transaction = connection.begin()
            acquired = connection.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": self.advisory_lock_id}
            ).scalar_one()
            if not acquired:
                transaction.rollback()
                raise CatalogLockUnavailable("another catalog mutation is active")
            try:
                yield connection
                transaction.commit()
            except BaseException:
                transaction.rollback()
                raise
            finally:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": self.advisory_lock_id}
                )

    def get_model_entry(
        self, model_version: str, *, connection: Connection | None = None
    ) -> ModelEntry | None:
        statement = text("SELECT * FROM catalog.model_entries WHERE model_version=:model_version")
        if connection is not None:
            row = connection.execute(statement, {"model_version": model_version}).mappings().first()
        else:
            with self.engine.connect() as local:
                row = local.execute(statement, {"model_version": model_version}).mappings().first()
        return ModelEntry.model_validate(dict(row)) if row else None

    def list_model_entries(
        self,
        *,
        integrity: str | None = None,
        lifecycle: str | None = None,
        connection: Connection | None = None,
    ) -> list[ModelEntry]:
        clauses: list[str] = []
        values: dict[str, Any] = {}
        if integrity:
            clauses.append("integrity_status=:integrity")
            values["integrity"] = integrity
        if lifecycle:
            clauses.append("lifecycle_status=:lifecycle")
            values["lifecycle"] = lifecycle
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        if connection is not None:
            rows = connection.execute(
                text(f"SELECT * FROM catalog.model_entries{where} ORDER BY first_seen_at"), values
            ).mappings()
            return [ModelEntry.model_validate(dict(row)) for row in rows]
        with self.engine.connect() as local:
            rows = local.execute(
                text(f"SELECT * FROM catalog.model_entries{where} ORDER BY first_seen_at"), values
            ).mappings()
            return [ModelEntry.model_validate(dict(row)) for row in rows]

    def upsert_model_entry(
        self, entry: ModelEntry, *, connection: Connection | None = None
    ) -> ModelEntry:
        statement = text(
            """
            INSERT INTO catalog.model_entries
              (model_version, manifest_schema_version, manifest_sha256, model_sha256,
               package_relpath, training_run_id, source_mlflow_run_id,
               source_mlflow_model_version, active_mlflow_run_id,
               active_mlflow_model_version, registered_model_name, integrity_status,
               catalog_status, lifecycle_status, promotion_status, diagnostic_code,
               first_seen_at, verified_at, last_reconciled_at, revision)
            VALUES
              (:model_version, :manifest_schema_version, :manifest_sha256, :model_sha256,
               :package_relpath, :training_run_id, :source_mlflow_run_id,
               :source_mlflow_model_version, :active_mlflow_run_id,
               :active_mlflow_model_version, :registered_model_name, :integrity_status,
               :catalog_status, :lifecycle_status, :promotion_status, :diagnostic_code,
               :first_seen_at, :verified_at, :last_reconciled_at, :revision)
            ON CONFLICT (model_version) DO UPDATE SET
              manifest_schema_version=EXCLUDED.manifest_schema_version,
              manifest_sha256=EXCLUDED.manifest_sha256,
              model_sha256=EXCLUDED.model_sha256,
              package_relpath=EXCLUDED.package_relpath,
              active_mlflow_run_id=EXCLUDED.active_mlflow_run_id,
              active_mlflow_model_version=EXCLUDED.active_mlflow_model_version,
              integrity_status=EXCLUDED.integrity_status,
              catalog_status=EXCLUDED.catalog_status,
              lifecycle_status=EXCLUDED.lifecycle_status,
              promotion_status=EXCLUDED.promotion_status,
              diagnostic_code=EXCLUDED.diagnostic_code,
              verified_at=EXCLUDED.verified_at,
              last_reconciled_at=EXCLUDED.last_reconciled_at,
              revision=catalog.model_entries.revision + 1
            RETURNING *
            """
        )
        values = _parameters(entry)
        if connection is not None:
            row = connection.execute(statement, values).mappings().one()
        else:
            with self.engine.begin() as local:
                row = local.execute(statement, values).mappings().one()
        return ModelEntry.model_validate(dict(row))

    def update_model_entry(
        self,
        model_version: str,
        expected_revision: int,
        changes: Mapping[str, Any],
        *,
        connection: Connection | None = None,
    ) -> ModelEntry:
        allowed = {
            "active_mlflow_run_id",
            "active_mlflow_model_version",
            "integrity_status",
            "catalog_status",
            "lifecycle_status",
            "promotion_status",
            "diagnostic_code",
            "verified_at",
            "last_reconciled_at",
        }
        if not changes or not set(changes).issubset(allowed):
            raise ValueError("unsupported or empty model entry update")
        assignments = ", ".join(f"{name}=:{name}" for name in sorted(changes))
        values = {**changes, "model_version": model_version, "revision": expected_revision}
        for key, value in tuple(values.items()):
            if hasattr(value, "value"):
                values[key] = value.value
        statement = text(
            f"UPDATE catalog.model_entries SET {assignments}, revision=revision+1 "
            "WHERE model_version=:model_version AND revision=:revision RETURNING *"
        )
        if connection is not None:
            row = connection.execute(statement, values).mappings().first()
        else:
            with self.engine.begin() as local:
                row = local.execute(statement, values).mappings().first()
        if not row:
            raise CatalogPersistenceError("catalog entry revision conflict")
        return ModelEntry.model_validate(dict(row))

    def append_event(self, event: OperationEvent, *, connection: Connection | None = None) -> None:
        statement = text(
            """
            INSERT INTO catalog.operation_events
              (event_id, operation_id, operation, model_version, from_state, to_state,
               phase, result, reason_code, occurred_at)
            VALUES
              (:event_id, :operation_id, :operation, :model_version,
               CAST(:from_state AS jsonb), CAST(:to_state AS jsonb), :phase, :result,
               :reason_code, :occurred_at)
            ON CONFLICT (event_id) DO NOTHING
            """
        )
        values = _parameters(event)
        values["from_state"] = (
            json.dumps(event.from_state) if event.from_state is not None else None
        )
        values["to_state"] = json.dumps(event.to_state) if event.to_state is not None else None
        if connection is not None:
            connection.execute(statement, values)
        else:
            with self.engine.begin() as local:
                local.execute(statement, values)

    def save_reconciliation(
        self, run: ReconciliationRun, *, connection: Connection | None = None
    ) -> None:
        run_statement = text(
            """
            INSERT INTO catalog.reconciliation_runs
              (reconciliation_id, trigger, mode, scan_fingerprint, status, started_at,
               completed_at, scanned_count, registered_count, recovered_count,
               quarantined_count, unchanged_count, mlflow_evidence_run_id)
            VALUES
              (:reconciliation_id, :trigger, :mode, :scan_fingerprint, :status, :started_at,
               :completed_at, :scanned_count, :registered_count, :recovered_count,
               :quarantined_count, :unchanged_count, :mlflow_evidence_run_id)
            ON CONFLICT (reconciliation_id) DO UPDATE SET
              status=EXCLUDED.status, completed_at=EXCLUDED.completed_at,
              scanned_count=EXCLUDED.scanned_count,
              registered_count=EXCLUDED.registered_count,
              recovered_count=EXCLUDED.recovered_count,
              quarantined_count=EXCLUDED.quarantined_count,
              unchanged_count=EXCLUDED.unchanged_count,
              mlflow_evidence_run_id=EXCLUDED.mlflow_evidence_run_id
            """
        )
        item_statement = text(
            """
            INSERT INTO catalog.reconciliation_items
              (reconciliation_id, package_relpath, model_version, manifest_sha256,
               action, result, reason_code, mlflow_run_id, mlflow_model_version, occurred_at)
            VALUES
              (:reconciliation_id, :package_relpath, :model_version, :manifest_sha256,
               :action, :result, :reason_code, :mlflow_run_id, :mlflow_model_version, :occurred_at)
            ON CONFLICT (reconciliation_id, package_relpath) DO NOTHING
            """
        )
        owns = connection is None
        context = self.engine.begin() if owns else _null_context(connection)
        with context as active:
            values = _parameters(run)
            values.pop("items")
            active.execute(run_statement, values)
            for item in run.items:
                active.execute(
                    item_statement,
                    {"reconciliation_id": str(run.reconciliation_id), **_parameters(item)},
                )

    def save_deletion_request(
        self, request: DeletionRequest, *, connection: Connection | None = None
    ) -> None:
        statement = text(
            """
            INSERT INTO catalog.deletion_requests
              (deletion_id, model_version, requested_at, confirmed_at, state,
               package_relpath, trash_relpath, impact, reason_code)
            VALUES
              (:deletion_id, :model_version, :requested_at, :confirmed_at, :state,
               :package_relpath, :trash_relpath, CAST(:impact AS jsonb), :reason_code)
            ON CONFLICT (deletion_id) DO UPDATE SET
              confirmed_at=EXCLUDED.confirmed_at, state=EXCLUDED.state,
              trash_relpath=EXCLUDED.trash_relpath, reason_code=EXCLUDED.reason_code
            """
        )
        values = _parameters(request)
        if connection is not None:
            connection.execute(statement, values)
        else:
            with self.engine.begin() as local:
                local.execute(statement, values)

    def tombstone_exists(self, model_version: str) -> bool:
        with self.engine.connect() as connection:
            return bool(
                connection.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM catalog.deletion_requests "
                        "WHERE model_version=:model_version "
                        "AND state IN ('confirmed','trashed','purged'))"
                    ),
                    {"model_version": model_version},
                ).scalar_one()
            )

    def get_deletion_request(
        self, deletion_id: UUID, *, connection: Connection | None = None
    ) -> DeletionRequest | None:
        statement = text(
            "SELECT * FROM catalog.deletion_requests WHERE deletion_id=:deletion_id"
        )
        values = {"deletion_id": str(deletion_id)}
        if connection is not None:
            row = connection.execute(statement, values).mappings().first()
        else:
            with self.engine.connect() as local:
                row = local.execute(statement, values).mappings().first()
        return DeletionRequest.model_validate(dict(row)) if row else None

    def get_active_deletion(
        self, model_version: str, *, connection: Connection | None = None
    ) -> DeletionRequest | None:
        statement = text(
            "SELECT * FROM catalog.deletion_requests WHERE model_version=:model_version "
            "AND state IN ('confirmed','trashed') ORDER BY requested_at DESC LIMIT 1"
        )
        if connection is not None:
            row = connection.execute(statement, {"model_version": model_version}).mappings().first()
        else:
            with self.engine.connect() as local:
                row = local.execute(
                    statement, {"model_version": model_version}
                ).mappings().first()
        return DeletionRequest.model_validate(dict(row)) if row else None

    def active_mutation_exists(self, model_version: str) -> bool:
        with self.engine.connect() as connection:
            return bool(
                connection.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM catalog.operation_events "
                        "WHERE model_version=:model_version AND result='started' AND NOT EXISTS ("
                        "SELECT 1 FROM catalog.operation_events terminal "
                        "WHERE terminal.operation_id=catalog.operation_events.operation_id "
                        "AND terminal.result IN ('succeeded','failed','compensated')))"
                    ),
                    {"model_version": model_version},
                ).scalar_one()
            )


@contextmanager
def _null_context(connection: Connection) -> Iterator[Connection]:
    yield connection


def utcnow() -> datetime:
    return datetime.now(UTC)
