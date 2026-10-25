import shutil
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

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


class ReadOnlyRepository:
    def __init__(self, entry: ModelEntry) -> None:
        self.entry = entry
        self.mutations = 0

    def get_model_entry(self, model_version, **_kwargs):
        return self.entry if model_version == self.entry.model_version else None

    def list_model_entries(self, **_kwargs):
        return [self.entry]


class ReadOnlyTracking:
    experiment_name = "house-price-training-v2"

    def __init__(self, package: Path, entry: ModelEntry) -> None:
        self.package = package
        self.entry = entry

    def assert_server_version(self):
        return "3.17.2"

    def active_artifact_location(self):
        return "mlflow-artifacts:/"

    def find_model_version(self, model_version):
        if model_version != self.entry.model_version:
            return None
        return SimpleNamespace(
            version=self.entry.active_mlflow_model_version,
            run_id=self.entry.active_mlflow_run_id,
            tags={
                "catalog.model_version": self.entry.model_version,
                "catalog.manifest_sha256": self.entry.manifest_sha256,
                "catalog.model_sha256": self.entry.model_sha256,
                "catalog.integrity": "verified",
                "catalog.publication_state": "approved",
            },
        )

    def get_run(self, run_id):
        return SimpleNamespace(info=SimpleNamespace(run_id=run_id))

    def get_champion_version(self):
        return self.entry.active_mlflow_model_version

    def download_artifacts(self, _run_id, path, destination):
        target = Path(destination) / Path(path).name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.package / "manifest.json", target)
        return target


def test_verify_cross_checks_package_ledger_mlflow_alias_and_pointer(
    project_root: Path, tmp_path: Path
) -> None:
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
        source_mlflow_model_version=manifest.mlflow_model_version,
        active_mlflow_run_id=manifest.mlflow_run_id,
        active_mlflow_model_version=manifest.mlflow_model_version,
        integrity_status=IntegrityStatus.VERIFIED,
        catalog_status=CatalogStatus.REGISTERED,
        lifecycle_status=LifecycleStatus.ACTIVE,
        promotion_status=PromotionStatus.CHAMPION,
        first_seen_at=datetime.now(UTC),
        verified_at=datetime.now(UTC),
    )
    repository = ReadOnlyRepository(entry)
    report = CatalogReconciler(
        root,
        repository=repository,
        tracking=ReadOnlyTracking(package, entry),
        minimum_free_bytes=1,
    ).verify()
    assert report["status"] == "succeeded"
    assert report["items"][0]["model_version"] == "fixture-v1"
    assert repository.mutations == 0


def test_failed_mlflow_run_is_auditable_but_not_a_valid_version(tmp_path: Path) -> None:
    from house_price.tracking.mlflow_client import TrackingClient

    client = TrackingClient(f"sqlite:///{tmp_path / 'failed.db'}", "failed-publication")
    run = client.client.create_run(
        client.client.get_experiment_by_name("failed-publication").experiment_id,
        tags={"catalog.publication_state": "failed", "diagnostic_code": "publication_failed"},
    )
    client.client.set_terminated(run.info.run_id, status="FAILED")
    persisted = client.client.get_run(run.info.run_id)
    assert persisted.info.status == "FAILED"
    assert client.find_model_version("missing") is None
