import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from house_price.catalog.models import (
    CatalogStatus,
    IntegrityStatus,
    LifecycleStatus,
    ModelEntry,
    PromotionStatus,
)
from house_price.catalog.reconciliation import CatalogReconciler
from house_price.registry.atomic import sha256_file
from house_price.registry.manifest import validate_package
from tests.integration.test_catalog_queries import ReadOnlyRepository, ReadOnlyTracking


def _fixture(project_root: Path, tmp_path: Path) -> tuple[Path, Path, ModelEntry]:
    root = tmp_path / "registry"
    shutil.copytree(project_root / "tests/fixtures/model-registry", root)
    package = root / "models/fixture-v1"
    manifest = validate_package(package)
    entry = ModelEntry(
        model_version=manifest.model_version,
        manifest_schema_version=manifest.schema_version,
        manifest_sha256=sha256_file(package / "manifest.json"),
        model_sha256=manifest.model_checksum,
        package_relpath="models/fixture-v1",
        training_run_id=manifest.training_run_id,
        source_mlflow_run_id=manifest.mlflow_run_id,
        active_mlflow_run_id=manifest.mlflow_run_id,
        active_mlflow_model_version=manifest.mlflow_model_version,
        integrity_status=IntegrityStatus.VERIFIED,
        catalog_status=CatalogStatus.REGISTERED,
        lifecycle_status=LifecycleStatus.ACTIVE,
        promotion_status=PromotionStatus.CHAMPION,
        first_seen_at=datetime.now(UTC),
        verified_at=datetime.now(UTC),
    )
    return root, package, entry


@pytest.mark.parametrize(
    ("pointer_state", "reason"),
    [("missing", "pointer_divergence"), ("corrupt", "pointer_invalid")],
)
def test_missing_or_corrupt_pointer_is_reported_without_repair(
    project_root: Path, tmp_path: Path, pointer_state: str, reason: str
) -> None:
    root, package, entry = _fixture(project_root, tmp_path)
    pointer = root / "current.json"
    if pointer_state == "missing":
        pointer.unlink()
    else:
        pointer.write_text("{not-json")
    before = pointer.read_bytes() if pointer.exists() else None
    report = CatalogReconciler(
        root,
        repository=ReadOnlyRepository(entry),
        tracking=ReadOnlyTracking(package, entry),
        minimum_free_bytes=1,
    ).verify()
    assert report["status"] == "partial"
    assert report["items"][0]["reason_codes"] == [reason]
    assert (pointer.read_bytes() if pointer.exists() else None) == before


def test_divergent_alias_and_newer_database_are_reported(
    project_root: Path, tmp_path: Path
) -> None:
    root, package, entry = _fixture(project_root, tmp_path)
    tracking = ReadOnlyTracking(package, entry)
    tracking.get_champion_version = lambda: "newer-mlflow-version"
    report = CatalogReconciler(
        root,
        repository=ReadOnlyRepository(entry),
        tracking=tracking,
        minimum_free_bytes=1,
    ).verify()
    assert report["status"] == "partial"
    assert "alias_divergence" in report["items"][0]["reason_codes"]


def test_newer_volume_and_newer_tombstone_are_classified_without_resurrection(
    project_root: Path, tmp_path: Path
) -> None:
    from tests.integration.test_catalog_reconciliation import MemoryRepository, MemoryTracking

    root, _package, _entry = _fixture(project_root, tmp_path)
    repository = MemoryRepository()
    repository.tombstones.add("fixture-v1")
    report = CatalogReconciler(
        root,
        repository=repository,
        tracking=MemoryTracking(),
        minimum_free_bytes=1,
    ).reconcile(mode="apply", trigger="restore")
    assert report["items"][0]["reason_code"] == "tombstoned_package"
    assert repository.entries == {}


def test_missing_artifact_store_is_a_preflight_failure(
    project_root: Path, tmp_path: Path
) -> None:
    root, package, entry = _fixture(project_root, tmp_path)
    tracking = ReadOnlyTracking(package, entry)

    def unavailable():
        raise ConnectionError("artifact store unavailable")

    tracking.active_artifact_location = unavailable
    service = CatalogReconciler(
        root,
        repository=ReadOnlyRepository(entry),
        tracking=tracking,
        minimum_free_bytes=1,
    )
    with pytest.raises(ConnectionError, match="artifact store unavailable"):
        service.preflight()


def test_restore_check_does_not_change_pointer_bytes(
    project_root: Path, tmp_path: Path
) -> None:
    root, package, entry = _fixture(project_root, tmp_path)
    pointer = root / "current.json"
    value = json.loads(pointer.read_text())
    value["model_version"] = "missing-version"
    pointer.write_text(json.dumps(value, sort_keys=True))
    before = pointer.read_bytes()
    CatalogReconciler(
        root,
        repository=ReadOnlyRepository(entry),
        tracking=ReadOnlyTracking(package, entry),
        minimum_free_bytes=1,
    ).verify()
    assert pointer.read_bytes() == before
