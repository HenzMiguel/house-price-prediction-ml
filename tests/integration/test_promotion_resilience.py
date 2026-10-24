import json
import os
import shutil
from pathlib import Path

import pytest

from house_price.registry.promotion import PromotionManager


class FakeTracking:
    def __init__(self, current: str | None = None) -> None:
        self.current = current
        self.set_calls: list[str] = []
        self.restore_calls: list[str | None] = []

    def get_champion_version(self) -> str | None:
        return self.current

    def set_champion(self, version: str) -> None:
        self.set_calls.append(version)
        self.current = version

    def restore_champion(self, version: str | None) -> None:
        self.restore_calls.append(version)
        self.current = version


def copy_package(project_root: Path, tmp_path: Path, name: str = "staging") -> Path:
    source = project_root / "tests/fixtures/model-registry/models/fixture-v1"
    destination = tmp_path / name
    shutil.copytree(source, destination)
    return destination


def test_successful_promotion_coordinates_alias_and_pointer(project_root, tmp_path) -> None:
    root = tmp_path / "registry"
    root.mkdir()
    tracking = FakeTracking("previous")
    version, promoted = PromotionManager(root, tracking).promote(
        copy_package(project_root, tmp_path), mlflow_version="2"
    )
    assert promoted and version == "fixture-v1"
    assert tracking.set_calls == ["2"]
    assert json.loads((root / "current.json").read_text())["model_version"] == "fixture-v1"


def test_duplicate_result_is_not_promoted_twice(project_root, tmp_path) -> None:
    root = tmp_path / "registry"
    root.mkdir()
    tracking = FakeTracking()
    manager = PromotionManager(root, tracking)
    manager.promote(copy_package(project_root, tmp_path, "first"), mlflow_version="1")
    _, promoted = manager.promote(
        copy_package(project_root, tmp_path, "duplicate"), mlflow_version="2"
    )
    assert not promoted
    assert tracking.set_calls == ["1"]


def test_pointer_failure_restores_previous_alias(project_root, tmp_path, monkeypatch) -> None:
    root = tmp_path / "registry"
    root.mkdir()
    tracking = FakeTracking("7")
    real_replace = os.replace

    def fail_pointer(source, destination):
        if Path(destination).name == "current.json":
            raise OSError("simulated pointer failure")
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_pointer)
    with pytest.raises(OSError, match="simulated"):
        PromotionManager(root, tracking).promote(
            copy_package(project_root, tmp_path), mlflow_version="8"
        )
    assert tracking.restore_calls == ["7"]
    assert not (root / "current.json").exists()


def test_corrupt_staging_never_changes_champion(project_root, tmp_path) -> None:
    root = tmp_path / "registry"
    root.mkdir()
    staging = copy_package(project_root, tmp_path)
    (staging / "model/model.joblib").write_bytes(b"corrupt")
    tracking = FakeTracking("1")
    with pytest.raises(ValueError, match="checksum"):
        PromotionManager(root, tracking).promote(staging, mlflow_version="2")
    assert tracking.set_calls == []
    assert tracking.current == "1"

