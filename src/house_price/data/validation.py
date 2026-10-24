"""Strict validation for the immutable training snapshot."""

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from house_price.domain import FEATURE_NAMES


class DatasetValidationError(ValueError):
    """Raised before any split or model fit when the snapshot is invalid."""


@dataclass(frozen=True)
class DatasetSnapshot:
    dataset_name: str
    dataset_version: str
    source_uri: str
    sha256: str
    row_count: int
    feature_names: tuple[str, ...]
    target_name: str
    created_at: datetime
    schema_version: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DatasetSnapshot":
        required = {
            "dataset_name",
            "dataset_version",
            "source_uri",
            "sha256",
            "row_count",
            "feature_names",
            "target_name",
            "created_at",
            "schema_version",
        }
        if set(value) != required:
            missing = required - set(value)
            extra = set(value) - required
            raise DatasetValidationError(
                f"manifest fields differ: missing={missing}, extra={extra}"
            )
        try:
            created_at = datetime.fromisoformat(str(value["created_at"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise DatasetValidationError("created_at must be ISO-8601") from exc
        snapshot = cls(
            dataset_name=str(value["dataset_name"]),
            dataset_version=str(value["dataset_version"]),
            source_uri=str(value["source_uri"]),
            sha256=str(value["sha256"]),
            row_count=int(value["row_count"]),
            feature_names=tuple(value["feature_names"]),
            target_name=str(value["target_name"]),
            created_at=created_at,
            schema_version=str(value["schema_version"]),
        )
        snapshot.validate_identity()
        return snapshot

    def validate_identity(self) -> None:
        if self.dataset_name != "california_housing":
            raise DatasetValidationError("unexpected dataset name")
        if not self.dataset_version or not self.source_uri or self.schema_version != "1.0.0":
            raise DatasetValidationError("dataset identity fields must be non-empty and versioned")
        if len(self.sha256) != 64 or any(c not in "0123456789abcdef" for c in self.sha256):
            raise DatasetValidationError("sha256 must contain 64 lowercase hexadecimal characters")
        if self.row_count != 20_640:
            raise DatasetValidationError("snapshot must contain exactly 20,640 rows")
        if self.feature_names != FEATURE_NAMES or self.target_name != "MedHouseVal":
            raise DatasetValidationError("snapshot schema does not match canonical feature order")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_and_validate_snapshot(
    dataset_path: Path, manifest_path: Path
) -> tuple[pd.DataFrame, DatasetSnapshot]:
    if not dataset_path.is_file() or not manifest_path.is_file():
        raise DatasetValidationError("dataset or manifest is missing")
    try:
        raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetValidationError("manifest is unreadable") from exc
    snapshot = DatasetSnapshot.from_dict(raw_manifest)
    if file_sha256(dataset_path) != snapshot.sha256:
        raise DatasetValidationError("dataset checksum differs from manifest")
    try:
        frame = pd.read_parquet(dataset_path)
    except Exception as exc:
        raise DatasetValidationError("dataset cannot be read as Parquet") from exc
    expected_columns = [*FEATURE_NAMES, "MedHouseVal"]
    if list(frame.columns) != expected_columns:
        raise DatasetValidationError("columns are missing, extra, or out of canonical order")
    if len(frame) != snapshot.row_count:
        raise DatasetValidationError("row count differs from manifest")
    if not all(pd.api.types.is_numeric_dtype(frame[column]) for column in frame.columns):
        raise DatasetValidationError("all feature and target columns must be numeric")
    values = frame.to_numpy(dtype=float)
    if frame.isna().any().any() or not np.isfinite(values).all():
        raise DatasetValidationError("null, NaN, or infinite values are forbidden")
    if frame.duplicated().any():
        raise DatasetValidationError("duplicate records are forbidden")
    if not all(math.isfinite(float(value)) for value in values.ravel()):
        raise DatasetValidationError("all values must be finite")
    return frame, snapshot
