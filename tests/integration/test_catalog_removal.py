import shutil
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from house_price.catalog import CatalogProtectedOperationError
from house_price.catalog.models import (
    CatalogStatus,
    IntegrityStatus,
    LifecycleStatus,
    ModelEntry,
    PromotionStatus,
)
from house_price.catalog.removal import CatalogRemoval


def _entry(version: str, mlflow_version: str, promotion: PromotionStatus) -> ModelEntry:
    return ModelEntry(
        model_version=version,
        manifest_schema_version="2.0.0",
        manifest_sha256="a" * 64,
        model_sha256="b" * 64,
        package_relpath=f"models/{version}",
        training_run_id="11111111-1111-4111-8111-111111111111",
        active_mlflow_run_id=f"run-{version}",
        active_mlflow_model_version=mlflow_version,
        integrity_status=IntegrityStatus.VERIFIED,
        catalog_status=CatalogStatus.REGISTERED,
        lifecycle_status=LifecycleStatus.ACTIVE,
        promotion_status=promotion,
        first_seen_at=datetime.now(UTC),
        verified_at=datetime.now(UTC),
    )


class MemoryRemovalRepository:
    def __init__(self, entries):
        self.entries = {entry.model_version: entry for entry in entries}
        self.requests = {}
        self.events = []
        self.active = set()

    @contextmanager
    def mutation_lock(self):
        yield object()

    def get_model_entry(self, version, **_kwargs):
        return self.entries.get(version)

    def list_model_entries(self, **_kwargs):
        return list(self.entries.values())

    def active_mutation_exists(self, version):
        return version in self.active

    def get_active_deletion(self, version, **_kwargs):
        return next(
            (
                item
                for item in self.requests.values()
                if item.model_version == version and item.state in {"confirmed", "trashed"}
            ),
            None,
        )

    def get_deletion_request(self, deletion_id, **_kwargs):
        return self.requests.get(deletion_id)

    def save_deletion_request(self, request, **_kwargs):
        self.requests[request.deletion_id] = request

    def update_model_entry(self, version, _revision, changes, **_kwargs):
        current = self.entries[version]
        updated = current.model_copy(
            update={**changes, "revision": current.revision + 1}
        )
        self.entries[version] = updated
        return updated

    def append_event(self, event, **_kwargs):
        self.events.append(event)


class MemoryRemovalTracking:
    def __init__(self, champion="1"):
        self.champion = champion
        self.deleted = []

    def get_champion_version(self):
        return self.champion

    def delete_model_version(self, version):
        self.deleted.append(version)


def _service(project_root: Path, tmp_path: Path):
    root = tmp_path / "registry"
    shutil.copytree(project_root / "tests/fixtures/model-registry", root)
    source = root / "models/fixture-v1"
    candidate = root / "models/candidate-v2"
    shutil.copytree(source, candidate)
    repository = MemoryRemovalRepository(
        [
            _entry("fixture-v1", "1", PromotionStatus.CHAMPION),
            _entry("candidate-v2", "2", PromotionStatus.SUPERSEDED),
        ]
    )
    tracking = MemoryRemovalTracking()
    return root, repository, tracking, CatalogRemoval(root, repository, tracking)


def test_delete_is_dry_run_by_default_and_reports_impact(
    project_root: Path, tmp_path: Path
) -> None:
    root, repository, tracking, service = _service(project_root, tmp_path)
    report = service.delete("candidate-v2")
    assert report["allowed"] is True
    assert report["confirmation_token"] == "candidate-v2"
    assert (root / "models/candidate-v2").is_dir()
    assert repository.requests == {}
    assert tracking.deleted == []


def test_delete_requires_exact_confirmation_and_protects_champion(
    project_root: Path, tmp_path: Path
) -> None:
    _root, _repository, _tracking, service = _service(project_root, tmp_path)
    with pytest.raises(CatalogProtectedOperationError, match="exactly match"):
        service.delete("candidate-v2", apply=True, confirmation="wrong")
    impact = service.delete("fixture-v1")
    assert impact["allowed"] is False
    assert set(impact["reason_codes"]) == {"champion_alias", "pointer_target"}


def test_delete_creates_tombstone_moves_atomically_and_retry_is_idempotent(
    project_root: Path, tmp_path: Path
) -> None:
    root, repository, tracking, service = _service(project_root, tmp_path)
    result = service.delete("candidate-v2", apply=True, confirmation="candidate-v2")
    deletion_id = result["deletion_id"]
    trash = root / f".trash/{deletion_id}/candidate-v2"
    assert trash.is_dir()
    assert not (root / "models/candidate-v2").exists()
    assert repository.entries["candidate-v2"].lifecycle_status is LifecycleStatus.TRASHED
    assert tracking.deleted == ["2"]
    retry = service.delete("candidate-v2", apply=True, confirmation="candidate-v2")
    assert retry["idempotent"] is True
    assert retry["deletion_id"] == deletion_id
    assert tracking.deleted == ["2"]


def test_separate_exactly_confirmed_purge_is_irreversible(
    project_root: Path, tmp_path: Path
) -> None:
    root, repository, _tracking, service = _service(project_root, tmp_path)
    deleted = service.delete("candidate-v2", apply=True, confirmation="candidate-v2")
    deletion_id = deleted["deletion_id"]
    with pytest.raises(CatalogProtectedOperationError, match="exact deletion ID"):
        service.purge(UUID(deletion_id), confirmation="wrong")
    result = service.purge(next(iter(repository.requests)), confirmation=deletion_id)
    assert result["state"] == "purged"
    assert not (root / f".trash/{deletion_id}/candidate-v2").exists()
    assert repository.entries["candidate-v2"].lifecycle_status is LifecycleStatus.DELETED


@pytest.mark.parametrize("protection", ["last", "mutation"])
def test_last_integral_model_and_active_mutation_are_refused(
    project_root: Path, tmp_path: Path, protection: str
) -> None:
    _root, repository, tracking, service = _service(project_root, tmp_path)
    if protection == "last":
        repository.entries["fixture-v1"] = repository.entries["fixture-v1"].model_copy(
            update={"lifecycle_status": LifecycleStatus.QUARANTINED}
        )
    else:
        repository.active.add("candidate-v2")
    tracking.champion = "1"
    impact = service.delete("candidate-v2")
    assert impact["allowed"] is False
    assert impact["reason_codes"] == [
        "last_integral_model" if protection == "last" else "mutation_active"
    ]
