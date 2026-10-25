"""Versioned immutable package manifests validated before model deserialization."""

import json
import math
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from house_price.domain import FEATURE_NAMES, CandidateFamily
from house_price.registry.atomic import safe_relative_path, sha256_file

SHA256_RE = r"^[a-f0-9]{64}$"
MODEL_VERSION_RE = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"


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


class FiniteMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mae: float = Field(ge=0)
    mse: float = Field(ge=0)
    rmse: float = Field(ge=0)
    r2: float

    @model_validator(mode="after")
    def finite(self) -> "FiniteMetrics":
        if not all(math.isfinite(value) for value in (self.mae, self.mse, self.rmse, self.r2)):
            raise ValueError("metrics must be finite")
        return self


def _relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError(f"unsafe artifact path: {value}")
    return value


class ArtifactPathsV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_path: Literal["model"]
    metrics_path: Literal["metrics.json"]
    plots: list[str]

    @field_validator("plots")
    @classmethod
    def validate_paths(cls, values: list[str]) -> list[str]:
        for value in values:
            _relative(value)
            if not value.startswith("plots/"):
                raise ValueError(f"unsafe plot path: {value}")
        return values


class LegacyModelManifestV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0.0"]
    model_version: str = Field(pattern=MODEL_VERSION_RE)
    registered_model_name: Literal["house-price-regressor"]
    mlflow_model_version: str = Field(min_length=1)
    mlflow_run_id: str = Field(min_length=1)
    training_run_id: UUID
    candidate_family: CandidateFamily
    dataset: DatasetIdentity
    model_checksum: str = Field(pattern=SHA256_RE)
    dependency_lock_checksum: str = Field(pattern=SHA256_RE)
    training_environment_version: str = Field(min_length=1)
    metrics: FiniteMetrics
    signature: ModelSignature
    artifacts: ArtifactPathsV1
    promoted_at: datetime
    previous_model_version: str | None = None


class ArtifactPathsV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_format: Literal["mlflow"]
    model_path: Literal["model"]
    parameters_path: Literal["parameters.json"]
    metrics_path: Literal["metrics.json"]
    dependency_lock_path: Literal["requirements.lock"]
    plots: list[str]
    checksums: dict[str, str] = Field(min_length=4)

    @field_validator("plots")
    @classmethod
    def validate_plots(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("plot paths must be unique")
        for value in values:
            _relative(value)
            if not re.fullmatch(r"plots/[A-Za-z0-9._-]+", value):
                raise ValueError(f"unsafe plot path: {value}")
        return values

    @field_validator("checksums")
    @classmethod
    def validate_checksums(cls, values: dict[str, str]) -> dict[str, str]:
        for relative, checksum in values.items():
            _relative(relative)
            if not relative.startswith(("model/", "plots/")) and relative not in {
                "parameters.json",
                "metrics.json",
                "requirements.lock",
            }:
                raise ValueError(f"unsupported checksum path: {relative}")
            if not re.fullmatch(SHA256_RE, checksum):
                raise ValueError(f"invalid checksum for {relative}")
        return values


class PersistedModelManifestV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["2.0.0"]
    model_version: str = Field(pattern=MODEL_VERSION_RE)
    registered_model_name: Literal["house-price-regressor"]
    training_run_id: UUID
    source_mlflow_run_id: str = Field(min_length=1)
    source_mlflow_model_version: str | None = Field(default=None, min_length=1)
    candidate_family: CandidateFamily
    code_revision: str = Field(min_length=1)
    training_environment_version: str = Field(min_length=1)
    dataset: DatasetIdentity
    parameters: dict[str, str | int | float | bool | None]
    metrics: FiniteMetrics
    signature: ModelSignature
    artifacts: ArtifactPathsV2
    promoted_at: datetime
    previous_model_version: str | None = None

    @property
    def mlflow_run_id(self) -> str:
        return self.source_mlflow_run_id

    @property
    def mlflow_model_version(self) -> str | None:
        return self.source_mlflow_model_version

    @property
    def model_checksum(self) -> str:
        candidates = sorted(
            value
            for path, value in self.artifacts.checksums.items()
            if path in {"model/model.skops", "model/model.joblib", "model/model.pkl"}
        )
        if not candidates:
            raise ValueError("manifest lacks serialized model checksum")
        return candidates[0]


type ChampionManifest = LegacyModelManifestV1 | PersistedModelManifestV2


def load_manifest(path: Path) -> ChampionManifest:
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    version = raw.get("schema_version")
    if version == "1.0.0":
        return LegacyModelManifestV1.model_validate(raw)
    if version == "2.0.0":
        return PersistedModelManifestV2.model_validate(raw)
    raise ValueError(f"unsupported manifest schema: {version!r}")


def _reject_symlinks(package_dir: Path) -> None:
    if package_dir.is_symlink():
        raise ValueError("package directory cannot be a symlink")
    for path in package_dir.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"package contains symlink: {path.name}")


def _validate_v1(package_dir: Path, manifest: LegacyModelManifestV1) -> None:
    model_path = safe_relative_path(package_dir, manifest.artifacts.model_path)
    metrics_path = safe_relative_path(package_dir, manifest.artifacts.metrics_path)
    if not model_path.exists() or not metrics_path.is_file():
        raise ValueError("champion package is incomplete")
    model_file = model_path / "model.joblib" if model_path.is_dir() else model_path
    if not model_file.is_file() or sha256_file(model_file) != manifest.model_checksum:
        raise ValueError("model checksum mismatch")
    for plot in manifest.artifacts.plots:
        if not safe_relative_path(package_dir, plot).is_file():
            raise ValueError(f"missing plot: {plot}")
    raw_metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    if raw_metrics != manifest.metrics.model_dump():
        raise ValueError("metrics file does not match manifest")


def _validate_v2(package_dir: Path, manifest: PersistedModelManifestV2) -> None:
    required = {
        "model/MLmodel",
        manifest.artifacts.parameters_path,
        manifest.artifacts.metrics_path,
        manifest.artifacts.dependency_lock_path,
        *manifest.artifacts.plots,
    }
    if not required.issubset(manifest.artifacts.checksums):
        raise ValueError("manifest checksums do not cover required artifacts")
    observed = {
        path.relative_to(package_dir).as_posix()
        for path in package_dir.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if observed != set(manifest.artifacts.checksums):
        raise ValueError("manifest checksums must cover every package artifact")
    for relative, expected in manifest.artifacts.checksums.items():
        path = safe_relative_path(package_dir, relative)
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"artifact checksum mismatch: {relative}")
    metrics = json.loads(
        safe_relative_path(package_dir, manifest.artifacts.metrics_path).read_text(encoding="utf-8")
    )
    parameters = json.loads(
        safe_relative_path(package_dir, manifest.artifacts.parameters_path).read_text(
            encoding="utf-8"
        )
    )
    if metrics != manifest.metrics.model_dump() or parameters != manifest.parameters:
        raise ValueError("package metadata does not match manifest")


def validate_package(
    package_dir: Path, *, require_directory_identity: bool = False
) -> ChampionManifest:
    _reject_symlinks(package_dir)
    manifest = load_manifest(package_dir / "manifest.json")
    if require_directory_identity and package_dir.name != manifest.model_version:
        raise ValueError("package directory does not match model identity")
    if isinstance(manifest, LegacyModelManifestV1):
        _validate_v1(package_dir, manifest)
    else:
        _validate_v2(package_dir, manifest)
    return manifest


def model_file_for(manifest: ChampionManifest, package_dir: Path) -> Path:
    for relative in ("model/model.skops", "model/model.joblib", "model/model.pkl"):
        candidate = safe_relative_path(package_dir, relative)
        if candidate.is_file():
            return candidate
    raise ValueError("package has no supported serialized model file")


# Compatibility exports retained while v1 packages remain readable.
ArtifactPaths = ArtifactPathsV1
