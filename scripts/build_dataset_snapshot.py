#!/usr/bin/env python3
"""Build the immutable California Housing snapshot used by the trainer image."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sklearn.datasets import fetch_california_housing

from house_price.domain import FEATURE_NAMES


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_snapshot(output_dir: Path, version: str = "sklearn-california-housing-v1") -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    bunch = fetch_california_housing(as_frame=True)
    frame = bunch.data.loc[:, FEATURE_NAMES].copy()
    frame["MedHouseVal"] = bunch.target
    if len(frame) != 20_640:
        raise RuntimeError(f"unexpected source row count: {len(frame)}")

    dataset_path = output_dir / "california_housing.parquet"
    frame.to_parquet(dataset_path, index=False, compression="zstd")
    manifest = {
        "dataset_name": "california_housing",
        "dataset_version": version,
        "source_uri": "https://www.dcc.fc.up.pt/~ltorgo/Regression/cal_housing.html",
        "sha256": sha256_file(dataset_path),
        "row_count": 20_640,
        "feature_names": list(FEATURE_NAMES),
        "target_name": "MedHouseVal",
        "created_at": datetime.now(UTC).isoformat(),
        "schema_version": "1.0.0",
    }
    manifest_path = output_dir / "dataset-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument("--version", default="sklearn-california-housing-v1")
    args = parser.parse_args()
    print(json.dumps(build_snapshot(args.output_dir, args.version), sort_keys=True))


if __name__ == "__main__":
    main()
