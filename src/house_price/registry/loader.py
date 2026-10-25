"""Safe champion loading and last-known-good cache."""

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import joblib
import mlflow.pyfunc

from house_price.registry.manifest import (
    ChampionManifest,
    model_file_for,
    sha256_file,
    validate_package,
)
from house_price.registry.pointer import read_pointer


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
        pointer = read_pointer(self.root)
        if pointer is None:
            raise FileNotFoundError(pointer_path)
        manifest_rel = Path(pointer.manifest_path)
        manifest_path = self.root / manifest_rel
        if sha256_file(manifest_path) != pointer.manifest_sha256:
            raise ValueError("manifest checksum differs from pointer")
        package_dir = manifest_path.parent
        manifest = validate_package(package_dir, require_directory_identity=True)
        if manifest.model_version != pointer.model_version:
            raise ValueError("pointer and manifest model versions differ")
        if manifest.schema_version == "2.0.0":
            predictor = mlflow.pyfunc.load_model(str(package_dir / "model"))
        else:
            predictor = joblib.load(model_file_for(manifest, package_dir))
        loaded = LoadedChampion(manifest, predictor, pointer.manifest_sha256)
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
