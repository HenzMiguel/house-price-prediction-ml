import json
import shutil
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from house_price.catalog.reconciliation import CatalogReconciler


class MemoryRepository:
    def __init__(self) -> None:
        self.entries = {}
        self.runs = []
        self.events = []
        self.tombstones = set()

    @contextmanager
    def mutation_lock(self):
        yield object()

    def get_model_entry(self, version, **_kwargs):
        return self.entries.get(version)

    def upsert_model_entry(self, entry, **_kwargs):
        previous = self.entries.get(entry.model_version)
        if previous:
            entry = entry.model_copy(update={"revision": previous.revision + 1})
        self.entries[entry.model_version] = entry
        return entry

    def update_model_entry(self, version, _revision, changes, **_kwargs):
        entry = self.entries[version].model_copy(
            update={**changes, "revision": self.entries[version].revision + 1}
        )
        self.entries[version] = entry
        return entry

    def save_reconciliation(self, run, **_kwargs):
        self.runs.append(run)

    def append_event(self, event, **_kwargs):
        self.events.append(event)

    def tombstone_exists(self, version):
        return version in self.tombstones

    def list_model_entries(self, **_kwargs):
        return list(self.entries.values())


class MemoryTracking:
    experiment_name = "house-price-training-v2"

    def __init__(self) -> None:
        self.versions = {}
        self.version_creations = 0
        self.current = None

    def get_run(self, run_id):
        return SimpleNamespace(info=SimpleNamespace(run_id=run_id))

    def find_model_version(self, version):
        return self.versions.get(version)

    def register_model_version(self, *, run_id, model_version, tags, **_kwargs):
        self.version_creations += 1
        item = SimpleNamespace(version=str(self.version_creations), run_id=run_id, tags=dict(tags))
        self.versions[model_version] = item
        return item.version

    def get_champion_version(self):
        return self.current


def prepare_ten_packages(project_root: Path, root: Path) -> None:
    models = root / "models"
    models.mkdir(parents=True)
    source = project_root / "tests/fixtures/model-registry/models/fixture-v1"
    for index in range(10):
        version = f"fixture-{index}"
        package = models / version
        shutil.copytree(source, package)
        manifest_path = package / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["model_version"] = version
        manifest_path.write_text(json.dumps(manifest))
        if index >= 8:
            (package / "model/model.joblib").write_bytes(b"corrupt")


def test_ten_package_apply_is_idempotent_across_five_repetitions(
    project_root: Path, tmp_path: Path
) -> None:
    root = tmp_path / "registry"
    prepare_ten_packages(project_root, root)
    repository = MemoryRepository()
    tracking = MemoryTracking()
    service = CatalogReconciler(
        root, repository=repository, tracking=tracking, minimum_free_bytes=1
    )
    first = service.reconcile(mode="apply", trigger="manual")
    assert first["counts"]["scanned"] == 10
    assert first["counts"]["registered"] == 8
    assert first["counts"]["quarantined"] == 2
    for _ in range(4):
        report = service.reconcile(mode="apply", trigger="manual")
        assert report["counts"]["scanned"] == 10
    assert tracking.version_creations == 8
    assert len(repository.entries) == 8
    assert tracking.current is None

