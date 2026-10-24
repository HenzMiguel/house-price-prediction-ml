import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from house_price.data.validation import (
    DatasetSnapshot,
    DatasetValidationError,
    file_sha256,
    load_and_validate_snapshot,
)
from house_price.domain import FEATURE_NAMES


def test_repository_snapshot_is_valid(dataset_paths: tuple[Path, Path]) -> None:
    frame, snapshot = load_and_validate_snapshot(*dataset_paths)
    assert len(frame) == 20_640
    assert snapshot.dataset_name == "california_housing"
    assert snapshot.feature_names == FEATURE_NAMES
    assert snapshot.target_name == "MedHouseVal"
    assert len(snapshot.sha256) == 64


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dataset_name", "wrong"),
        ("dataset_version", ""),
        ("sha256", "x" * 64),
        ("row_count", 100),
        ("feature_names", [*reversed(FEATURE_NAMES)]),
        ("target_name", "price"),
    ],
)
def test_invalid_manifest_identity_is_rejected(
    dataset_paths: tuple[Path, Path], field: str, value: object
) -> None:
    manifest = json.loads(dataset_paths[1].read_text())
    manifest[field] = value
    with pytest.raises(DatasetValidationError):
        DatasetSnapshot.from_dict(manifest)


def _write_variant(tmp_path: Path, frame: pd.DataFrame, source_manifest: Path) -> tuple[Path, Path]:
    dataset = tmp_path / "variant.parquet"
    frame.to_parquet(dataset, index=False)
    manifest = json.loads(source_manifest.read_text())
    manifest["sha256"] = file_sha256(dataset)
    manifest["row_count"] = len(frame)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    return dataset, manifest_path


@pytest.mark.parametrize("mutation", ["null", "infinite", "duplicate", "extra", "missing"])
def test_invalid_data_is_rejected(
    dataset_paths: tuple[Path, Path], tmp_path: Path, mutation: str
) -> None:
    frame = pd.read_parquet(dataset_paths[0])
    if mutation == "null":
        frame.loc[0, "MedInc"] = np.nan
    elif mutation == "infinite":
        frame.loc[0, "MedInc"] = np.inf
    elif mutation == "duplicate":
        frame.iloc[1] = frame.iloc[0]
    elif mutation == "extra":
        frame["extra"] = 1.0
    else:
        frame = frame.drop(columns=["MedInc"])
    paths = _write_variant(tmp_path, frame, dataset_paths[1])
    with pytest.raises(DatasetValidationError):
        load_and_validate_snapshot(*paths)


def test_checksum_mismatch_is_rejected(dataset_paths: tuple[Path, Path], tmp_path: Path) -> None:
    manifest = json.loads(dataset_paths[1].read_text())
    manifest["sha256"] = "0" * 64
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(DatasetValidationError, match="checksum"):
        load_and_validate_snapshot(dataset_paths[0], path)

