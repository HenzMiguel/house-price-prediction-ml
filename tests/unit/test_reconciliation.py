import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from house_price.catalog.reconciliation import CatalogReconciler, scan_fingerprint


def reconciler(root: Path) -> CatalogReconciler:
    return CatalogReconciler(
        root,
        repository=SimpleNamespace(),
        tracking=SimpleNamespace(),
        minimum_free_bytes=1,
    )


def test_scanner_classifies_valid_corrupt_and_unsafe_packages(
    project_root: Path, tmp_path: Path
) -> None:
    root = tmp_path / "registry"
    models = root / "models"
    models.mkdir(parents=True)
    shutil.copytree(
        project_root / "tests/fixtures/model-registry/models/fixture-v1",
        models / "fixture-v1",
    )
    corrupt = models / "corrupt-v1"
    shutil.copytree(models / "fixture-v1", corrupt)
    manifest = json.loads((corrupt / "manifest.json").read_text())
    manifest["model_version"] = "corrupt-v1"
    (corrupt / "manifest.json").write_text(json.dumps(manifest))
    (corrupt / "model/model.joblib").write_bytes(b"corrupt")
    (models / "unsafe-v1").symlink_to(models / "fixture-v1", target_is_directory=True)

    scanned = reconciler(root).scan()
    assert [item.model_version for item in scanned] == [
        "corrupt-v1",
        "fixture-v1",
        "unsafe-v1",
    ]
    assert [item.error for item in scanned] == [
        "package_invalid",
        None,
        "unsafe_package_path",
    ]
    assert scan_fingerprint(scanned) == scan_fingerprint(scanned)


def test_scanner_ignores_staging_quarantine_and_trash(tmp_path: Path) -> None:
    for name in (".staging", ".quarantine", ".trash"):
        (tmp_path / name / "ignored").mkdir(parents=True)
    assert reconciler(tmp_path).scan() == []

