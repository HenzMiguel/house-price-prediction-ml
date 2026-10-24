"""Champion manifest and immutable package validation."""

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from house_price.domain import FEATURE_NAMES, CandidateFamily, ModelMetrics

SHA256_RE = r"^[a-f0-9]{64}$"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class DatasetIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Literal["california_housing"]
    version: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_RE)
    row_count: Literal[20640]
    schema_version: str = Field(min_length=1)


class SignatureField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    type: Literal["double"]


class ModelSignature(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: list[SignatureField] = Field(min_length=8, max_length=8)
    output: Literal["double"]

    @model_validator(mode="after")
    def validate_feature_order(self) -> "ModelSignature":
        if tuple(item.name for item in self.inputs) != FEATURE_NAMES:
            raise ValueError("signature inputs must use canonical feature order")
        return self


class ArtifactPaths(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_path: Literal["model"]
    metrics_path: Literal["metrics.json"]
    plots: list[str]

    @field_validator("plots")
    @classmethod
    def validate_paths(cls, values: list[str]) -> list[str]:
        for value in values:
            path = PurePosixPath(value)
            if path.is_absolute() or ".." in path.parts or not value.startswith("plots/"):
                raise ValueError(f"unsafe plot path: {value}")
        return values


class ChampionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0.0"]
    model_version: str = Field(min_length=1)
    registered_model_name: Literal["house-price-regressor"]
    mlflow_model_version: str = Field(min_length=1)
    mlflow_run_id: str = Field(min_length=1)
    training_run_id: UUID
    candidate_family: CandidateFamily
    dataset: DatasetIdentity
    model_checksum: str = Field(pattern=SHA256_RE)
    dependency_lock_checksum: str = Field(pattern=SHA256_RE)
    training_environment_version: str = Field(min_length=1)
    metrics: ModelMetrics
    signature: ModelSignature
    artifacts: ArtifactPaths
    promoted_at: datetime
    previous_model_version: str | None = None

    @field_validator("metrics")
    @classmethod
    def finite_metrics(cls, value: ModelMetrics) -> ModelMetrics:
        if not all(math.isfinite(x) for x in (value.mae, value.mse, value.rmse, value.r2)):
            raise ValueError("metrics must be finite")
        if min(value.mae, value.mse, value.rmse) < 0:
            raise ValueError("error metrics must be non-negative")
        return value


def load_manifest(path: Path) -> ChampionManifest:
    return ChampionManifest.model_validate_json(path.read_text(encoding="utf-8"))


def validate_package(package_dir: Path) -> ChampionManifest:
    manifest_path = package_dir / "manifest.json"
    manifest = load_manifest(manifest_path)
    model_path = package_dir / manifest.artifacts.model_path
    metrics_path = package_dir / manifest.artifacts.metrics_path
    if not model_path.exists() or not metrics_path.is_file():
        raise ValueError("champion package is incomplete")
    model_file = model_path / "model.joblib" if model_path.is_dir() else model_path
    if not model_file.is_file() or sha256_file(model_file) != manifest.model_checksum:
        raise ValueError("model checksum mismatch")
    for plot in manifest.artifacts.plots:
        if not (package_dir / plot).is_file():
            raise ValueError(f"missing plot: {plot}")
    raw_metrics: dict[str, Any] = json.loads(metrics_path.read_text(encoding="utf-8"))
    if raw_metrics != manifest.metrics.__dict__:
        raise ValueError("metrics file does not match manifest")
    return manifest
