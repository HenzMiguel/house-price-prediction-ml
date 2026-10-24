"""Coordinated immutable-volume and MLflow alias promotion."""

import hashlib
import json
import os
import shutil
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from house_price.registry.manifest import sha256_file, validate_package
from house_price.tracking.mlflow_client import TrackingClient

PROMOTION_LOCK_ID = 0x485052494345


def result_identity(
    *,
    code_revision: str,
    dataset_checksum: str,
    split_seed: int,
    test_fraction: float,
    family: str,
    parameters: dict[str, Any],
    model_checksum: str,
) -> str:
    canonical = json.dumps(
        {
            "code_revision": code_revision,
            "dataset_checksum": dataset_checksum,
            "split_seed": split_seed,
            "test_fraction": test_fraction,
            "family": family,
            "parameters": parameters,
            "model_checksum": model_checksum,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class ConcurrentPromotionError(RuntimeError):
    pass


class PromotionError(RuntimeError):
    """The candidate package could not be validated or atomically promoted."""



class PromotionManager:
    def __init__(
        self, root: Path, tracking: TrackingClient, *, lock_engine: Engine | None = None
    ) -> None:
        self.root = root
        self.tracking = tracking
        self.lock_engine = lock_engine

    @contextmanager
    def lock(self):
        if self.lock_engine is None:
            yield
            return
        with self.lock_engine.connect() as connection:
            acquired = connection.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": PROMOTION_LOCK_ID}
            ).scalar_one()
            if not acquired:
                raise ConcurrentPromotionError("another promotion is in progress")
            try:
                yield
            finally:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": PROMOTION_LOCK_ID}
                )

    def current_pointer(self) -> dict[str, Any] | None:
        path = self.root / "current.json"
        return json.loads(path.read_text()) if path.is_file() else None

    def promote(self, staging: Path, *, mlflow_version: str) -> tuple[str, bool]:
        manifest = validate_package(staging)
        with self.lock():
            return self.promote_locked(staging, mlflow_version=mlflow_version, manifest=manifest)

    def promote_locked(
        self,
        staging: Path,
        *,
        mlflow_version: str,
        manifest: Any | None = None,
    ) -> tuple[str, bool]:
        """Promote while the caller owns ``lock`` for a wider atomic operation."""
        manifest = manifest or validate_package(staging)
        model_version = manifest.model_version
        current = self.current_pointer()
        if current and current.get("model_version") == model_version:
            return model_version, False
        models = self.root / "models"
        models.mkdir(parents=True, exist_ok=True)
        destination = models / model_version
        if destination.exists():
            validate_package(destination)
        else:
            os.replace(staging, destination)
        previous_alias = self.tracking.get_champion_version()
        self.tracking.set_champion(mlflow_version)
        pointer = {
            "schema_version": "1.0.0",
            "model_version": model_version,
            "manifest_path": f"models/{model_version}/manifest.json",
            "manifest_sha256": sha256_file(destination / "manifest.json"),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        temporary = self.root / ".current.json.tmp"
        try:
            temporary.write_text(json.dumps(pointer, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(temporary, self.root / "current.json")
        except Exception:
            self.tracking.restore_champion(previous_alias)
            temporary.unlink(missing_ok=True)
            raise
        return model_version, True


def prepare_staging(source: Path, root: Path, model_version: str) -> Path:
    staging_root = root / ".staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    destination = staging_root / model_version
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    validate_package(destination)
    return destination
