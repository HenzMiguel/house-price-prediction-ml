import json
from pathlib import Path

import pytest

from house_price.registry.atomic import atomic_write_json, safe_relative_path, sha256_file
from house_price.registry.manifest import PersistedModelManifestV2, load_manifest, validate_package
from house_price.registry.pointer import ChampionPointer, write_pointer


def test_safe_relative_paths_and_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "registry"
    root.mkdir()
    assert safe_relative_path(root, "models/model-v2") == root / "models/model-v2"
    for unsafe in ("/absolute", "../escape", "models/../../escape"):
        with pytest.raises(ValueError, match="unsafe"):
            safe_relative_path(root, unsafe)
    target = root / "target"
    target.write_text("x")
    link = root / "link"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        safe_relative_path(root, "link")


def test_atomic_json_write_and_streaming_checksum(tmp_path: Path) -> None:
    path = tmp_path / "current.json"
    atomic_write_json(path, {"model_version": "v2"})
    assert json.loads(path.read_text()) == {"model_version": "v2"}
    assert sha256_file(path) == sha256_file(path)
    assert not list(tmp_path.glob("*.tmp"))


def test_pointer_write_is_atomic_and_preserves_previous_on_failure(tmp_path, monkeypatch) -> None:
    path = tmp_path / "current.json"
    previous = ChampionPointer(
        model_version="old",
        manifest_path="models/old/manifest.json",
        manifest_sha256="a" * 64,
    )
    write_pointer(path, previous)
    original = path.read_bytes()

    def fail_replace(*_args):
        raise OSError("replace failed")

    monkeypatch.setattr("house_price.registry.atomic.os.replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        write_pointer(
            path,
            ChampionPointer(
                model_version="new",
                manifest_path="models/new/manifest.json",
                manifest_sha256="b" * 64,
            ),
        )
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def test_v1_adapter_loads_existing_fixture(project_root: Path) -> None:
    package = project_root / "tests/fixtures/model-registry/models/fixture-v1"
    manifest = load_manifest(package / "manifest.json")
    assert manifest.schema_version == "1.0.0"
    assert validate_package(package).model_version == "fixture-v1"


def test_v2_validation_checks_every_declared_file(tmp_path: Path) -> None:
    package = tmp_path / "model-v2"
    (package / "model").mkdir(parents=True)
    (package / "model/MLmodel").write_text("flavors: {}\n")
    (package / "model/model.joblib").write_bytes(b"model")
    (package / "parameters.json").write_text("{}\n")
    (package / "metrics.json").write_text('{"mae":0.1,"mse":0.01,"r2":0.9,"rmse":0.1}\n')
    (package / "requirements.lock").write_text("dependency==1\n")
    checksums = {
        str(path.relative_to(package)): sha256_file(path)
        for path in package.rglob("*")
        if path.is_file()
    }
    manifest = {
        "schema_version": "2.0.0",
        "model_version": "model-v2",
        "registered_model_name": "house-price-regressor",
        "training_run_id": "00000000-0000-4000-8000-000000000001",
        "source_mlflow_run_id": "run-1",
        "source_mlflow_model_version": None,
        "candidate_family": "ridge",
        "code_revision": "abc",
        "training_environment_version": "env-v1",
        "dataset": {
            "name": "california_housing",
            "version": "v1",
            "sha256": "a" * 64,
            "row_count": 20640,
            "schema_version": "1.0.0",
        },
        "parameters": {},
        "metrics": {"mae": 0.1, "mse": 0.01, "rmse": 0.1, "r2": 0.9},
        "signature": {
            "inputs": [
                {"name": name, "type": "double"}
                for name in (
                    "MedInc",
                    "HouseAge",
                    "AveRooms",
                    "AveBedrms",
                    "Population",
                    "AveOccup",
                    "Latitude",
                    "Longitude",
                )
            ],
            "output": "double",
        },
        "artifacts": {
            "model_format": "mlflow",
            "model_path": "model",
            "parameters_path": "parameters.json",
            "metrics_path": "metrics.json",
            "dependency_lock_path": "requirements.lock",
            "plots": [],
            "checksums": checksums,
        },
        "promoted_at": "2026-10-25T12:00:00Z",
        "previous_model_version": None,
    }
    (package / "manifest.json").write_text(json.dumps(manifest))
    assert isinstance(validate_package(package), PersistedModelManifestV2)
    (package / "model/model.joblib").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        validate_package(package)
