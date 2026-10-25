from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from house_price.catalog.models import (
    CatalogStatus,
    IntegrityStatus,
    LifecycleStatus,
    ModelEntry,
    PromotionStatus,
    ReconciliationItem,
    ReconciliationRun,
)


def entry_values() -> dict[str, object]:
    return {
        "model_version": "model-v2",
        "manifest_schema_version": "2.0.0",
        "manifest_sha256": "a" * 64,
        "model_sha256": "b" * 64,
        "package_relpath": "models/model-v2",
        "training_run_id": uuid4(),
        "registered_model_name": "house-price-regressor",
        "integrity_status": IntegrityStatus.VERIFIED,
        "catalog_status": CatalogStatus.REGISTERED,
        "lifecycle_status": LifecycleStatus.ACTIVE,
        "promotion_status": PromotionStatus.CANDIDATE,
        "first_seen_at": datetime.now(UTC),
        "revision": 1,
    }


def test_model_entry_enforces_paths_checksums_and_registration() -> None:
    assert ModelEntry(**entry_values()).promotable
    for field, value in (("manifest_sha256", "A" * 64), ("package_relpath", "../model")):
        values = entry_values()
        values[field] = value
        with pytest.raises(ValidationError):
            ModelEntry(**values)
    values = entry_values()
    values.update(catalog_status=CatalogStatus.UNREGISTERED, active_mlflow_model_version="1")
    with pytest.raises(ValidationError, match="registered"):
        ModelEntry(**values)


def test_timestamps_must_be_utc_and_revision_positive() -> None:
    values = entry_values()
    values["first_seen_at"] = datetime(2026, 1, 1)
    with pytest.raises(ValidationError, match="timezone"):
        ModelEntry(**values)
    values = entry_values()
    values["revision"] = 0
    with pytest.raises(ValidationError):
        ModelEntry(**values)


def test_reconciliation_counts_and_item_paths_are_consistent() -> None:
    item = ReconciliationItem(
        package_relpath="models/model-v2",
        model_version="model-v2",
        manifest_sha256="a" * 64,
        action="verified",
        result="succeeded",
        occurred_at=datetime.now(UTC),
    )
    run = ReconciliationRun(
        reconciliation_id=uuid4(),
        trigger="manual",
        mode="check",
        scan_fingerprint="b" * 64,
        status="succeeded",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        scanned_count=1,
        unchanged_count=1,
        items=[item],
    )
    assert run.scanned_count == len(run.items)
    with pytest.raises(ValidationError):
        ReconciliationItem(
            package_relpath=".trash/model-v2",
            action="quarantined",
            result="failed",
            occurred_at=datetime.now(UTC),
        )
