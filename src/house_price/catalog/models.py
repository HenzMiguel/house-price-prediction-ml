"""Validated catalog records shared by persistence, reconciliation, and the CLI."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SHA256_RE = r"^[a-f0-9]{64}$"
MODEL_VERSION_RE = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
PACKAGE_RE = r"^models/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
REASON_RE = r"^[a-z][a-z0-9_]{0,63}$"


class IntegrityStatus(StrEnum):
    UNKNOWN = "unknown"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    INVALID = "invalid"
    MISSING = "missing"
    UNSUPPORTED = "unsupported"


class CatalogStatus(StrEnum):
    UNREGISTERED = "unregistered"
    REGISTERING = "registering"
    REGISTERED = "registered"
    REGISTRATION_FAILED = "registration_failed"
    CONFLICT = "conflict"


class LifecycleStatus(StrEnum):
    ACTIVE = "active"
    QUARANTINED = "quarantined"
    DELETION_REQUESTED = "deletion_requested"
    TRASHED = "trashed"
    DELETED = "deleted"


class PromotionStatus(StrEnum):
    CANDIDATE = "candidate"
    CHAMPION = "champion"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    @field_validator("*", mode="after")
    @classmethod
    def timezone_aware_datetimes(cls, value: Any) -> Any:
        if isinstance(value, datetime) and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("datetime must be timezone-aware")
        return value


class ModelEntry(StrictRecord):
    model_version: str = Field(pattern=MODEL_VERSION_RE)
    manifest_schema_version: Literal["1.0.0", "2.0.0"]
    manifest_sha256: str = Field(pattern=SHA256_RE)
    model_sha256: str = Field(pattern=SHA256_RE)
    package_relpath: str = Field(pattern=PACKAGE_RE)
    training_run_id: UUID
    source_mlflow_run_id: str | None = None
    source_mlflow_model_version: str | None = None
    active_mlflow_run_id: str | None = None
    active_mlflow_model_version: str | None = None
    registered_model_name: Literal["house-price-regressor"] = "house-price-regressor"
    integrity_status: IntegrityStatus = IntegrityStatus.UNKNOWN
    catalog_status: CatalogStatus = CatalogStatus.UNREGISTERED
    lifecycle_status: LifecycleStatus = LifecycleStatus.ACTIVE
    promotion_status: PromotionStatus = PromotionStatus.CANDIDATE
    diagnostic_code: str | None = Field(default=None, pattern=REASON_RE)
    first_seen_at: datetime
    verified_at: datetime | None = None
    last_reconciled_at: datetime | None = None
    revision: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def validate_links(self) -> "ModelEntry":
        if self.package_relpath != f"models/{self.model_version}":
            raise ValueError("package path must match model version")
        if self.active_mlflow_model_version and self.catalog_status is not CatalogStatus.REGISTERED:
            raise ValueError("active MLflow version requires registered catalog status")
        if self.promotion_status is PromotionStatus.CHAMPION and not self.promotable:
            raise ValueError("champion must be verified, registered, and active")
        return self

    @property
    def promotable(self) -> bool:
        return (
            self.integrity_status is IntegrityStatus.VERIFIED
            and self.catalog_status is CatalogStatus.REGISTERED
            and self.lifecycle_status is LifecycleStatus.ACTIVE
        )


class ReconciliationItem(StrictRecord):
    package_relpath: str = Field(pattern=PACKAGE_RE)
    model_version: str | None = Field(default=None, pattern=MODEL_VERSION_RE)
    manifest_sha256: str | None = Field(default=None, pattern=SHA256_RE)
    action: Literal["verified", "registered", "recovered", "quarantined", "unchanged", "conflict"]
    result: Literal["succeeded", "failed", "skipped"]
    reason_code: str | None = Field(default=None, pattern=REASON_RE)
    mlflow_run_id: str | None = None
    mlflow_model_version: str | None = None
    occurred_at: datetime


class ReconciliationRun(StrictRecord):
    reconciliation_id: UUID
    trigger: Literal["manual", "startup", "weekly", "restore"]
    mode: Literal["check", "apply"]
    scan_fingerprint: str = Field(pattern=SHA256_RE)
    status: Literal["running", "succeeded", "partial", "failed", "lock_unavailable"]
    started_at: datetime
    completed_at: datetime | None = None
    scanned_count: int = Field(default=0, ge=0)
    registered_count: int = Field(default=0, ge=0)
    recovered_count: int = Field(default=0, ge=0)
    quarantined_count: int = Field(default=0, ge=0)
    unchanged_count: int = Field(default=0, ge=0)
    mlflow_evidence_run_id: str | None = None
    items: list[ReconciliationItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_counts(self) -> "ReconciliationRun":
        if self.completed_at and self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        if any(
            value > self.scanned_count
            for value in (
                self.registered_count,
                self.recovered_count,
                self.quarantined_count,
                self.unchanged_count,
            )
        ):
            raise ValueError("result counts cannot exceed scanned count")
        if self.items and len(self.items) != self.scanned_count:
            raise ValueError("item count must equal scanned count")
        return self


class OperationEvent(StrictRecord):
    event_id: UUID
    operation_id: UUID
    operation: Literal["publish", "reconcile", "resolve_champion", "delete", "purge"]
    model_version: str | None = Field(default=None, pattern=MODEL_VERSION_RE)
    from_state: dict[str, Any] | None = None
    to_state: dict[str, Any] | None = None
    phase: str = Field(min_length=1)
    result: Literal["started", "succeeded", "failed", "compensated"]
    reason_code: str | None = Field(default=None, pattern=REASON_RE)
    occurred_at: datetime


class DeletionRequest(StrictRecord):
    deletion_id: UUID
    model_version: str = Field(pattern=MODEL_VERSION_RE)
    requested_at: datetime
    confirmed_at: datetime | None = None
    state: Literal["planned", "confirmed", "trashed", "purged", "refused", "failed"]
    package_relpath: str = Field(pattern=PACKAGE_RE)
    trash_relpath: str | None = None
    impact: dict[str, Any]
    reason_code: str | None = Field(default=None, pattern=REASON_RE)

    @model_validator(mode="after")
    def validate_deletion(self) -> "DeletionRequest":
        if self.state in {"refused", "failed"} and not self.reason_code:
            raise ValueError("refused and failed deletion requests require a reason")
        if self.trash_relpath and self.trash_relpath != (
            f".trash/{self.deletion_id}/{self.model_version}"
        ):
            raise ValueError("trash path must match deletion identity")
        return self
