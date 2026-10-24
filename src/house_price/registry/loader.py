"""Safe champion loading and last-known-good cache."""

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import joblib

from house_price.registry.manifest import ChampionManifest, sha256_file, validate_package


class Predictor(Protocol):
    def predict(self, values: Any) -> Any: ...


@dataclass(frozen=True)
class LoadedChampion:
    manifest: ChampionManifest
    predictor: Predictor
    pointer_checksum: str


class ChampionLoader:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.RLock()
        self._current: LoadedChampion | None = None
        self._pointer_mtime_ns: int | None = None

    @property
    def current(self) -> LoadedChampion | None:
        with self._lock:
            return self._current

    def load(self) -> LoadedChampion:
        pointer_path = self.root / "current.json"
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        required = {
            "schema_version",
            "model_version",
            "manifest_path",
            "manifest_sha256",
            "updated_at",
        }
        if set(pointer) != required or pointer["schema_version"] != "1.0.0":
            raise ValueError("invalid champion pointer")
        manifest_rel = Path(pointer["manifest_path"])
        if manifest_rel.is_absolute() or ".." in manifest_rel.parts:
            raise ValueError("unsafe manifest path")
        manifest_path = self.root / manifest_rel
        if sha256_file(manifest_path) != pointer["manifest_sha256"]:
            raise ValueError("manifest checksum differs from pointer")
        package_dir = manifest_path.parent
        manifest = validate_package(package_dir)
        if manifest.model_version != pointer["model_version"]:
            raise ValueError("pointer and manifest model versions differ")
        predictor = joblib.load(package_dir / manifest.artifacts.model_path / "model.joblib")
        loaded = LoadedChampion(manifest, predictor, pointer["manifest_sha256"])
        with self._lock:
            self._current = loaded
            self._pointer_mtime_ns = pointer_path.stat().st_mtime_ns
        return loaded

    def reload_if_changed(self) -> bool:
        pointer_path = self.root / "current.json"
        if not pointer_path.is_file():
            return False
        mtime = pointer_path.stat().st_mtime_ns
        with self._lock:
            if self._pointer_mtime_ns == mtime:
                return False
        self.load()
        return True

