import json
import shutil
from pathlib import Path

import pytest

from house_price.registry.loader import ChampionLoader


def fixture_copy(project_root: Path, tmp_path: Path) -> Path:
    source = project_root / "tests/fixtures/model-registry"
    destination = tmp_path / "registry"
    shutil.copytree(source, destination)
    return destination


def test_initial_load_validates_manifest_checksum_and_model(project_root, tmp_path) -> None:
    root = fixture_copy(project_root, tmp_path)
    loaded = ChampionLoader(root).load()
    assert loaded.manifest.model_version == "fixture-v1"
    assert len(loaded.predictor.predict([[1.0] * 8])) == 1


def test_failed_reload_preserves_previous_model(project_root, tmp_path) -> None:
    root = fixture_copy(project_root, tmp_path)
    loader = ChampionLoader(root)
    previous = loader.load()
    pointer_path = root / "current.json"
    pointer = json.loads(pointer_path.read_text())
    pointer["manifest_sha256"] = "0" * 64
    pointer_path.write_text(json.dumps(pointer))
    with pytest.raises(ValueError, match="checksum"):
        loader.reload_if_changed()
    assert loader.current is previous


def test_unsafe_manifest_path_is_rejected(project_root, tmp_path) -> None:
    root = fixture_copy(project_root, tmp_path)
    pointer_path = root / "current.json"
    pointer = json.loads(pointer_path.read_text())
    pointer["manifest_path"] = "../manifest.json"
    pointer_path.write_text(json.dumps(pointer))
    with pytest.raises(ValueError, match="unsafe"):
        ChampionLoader(root).load()

