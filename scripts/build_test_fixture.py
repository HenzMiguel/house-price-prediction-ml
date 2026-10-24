#!/usr/bin/env python3
"""Generate the deterministic champion package used by isolated API tests."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from house_price.domain import FEATURE_NAMES


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(root: Path) -> None:
    package = root / "models/fixture-v1"
    model_dir = package / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    x = pd.DataFrame(np.arange(80, dtype=float).reshape(10, 8) + 1, columns=FEATURE_NAMES)
    y = np.linspace(1, 2, 10)
    model = LinearRegression().fit(x, y)
    model_path = model_dir / "model.joblib"
    joblib.dump(model, model_path)
    (model_dir / "MLmodel").write_text(
        "artifact_path: model\nflavors:\n  sklearn:\n    pickled_model: model.joblib\n",
        encoding="utf-8",
    )
    metrics = {"mae": 0.1, "mse": 0.02, "rmse": 0.1414213562, "r2": 0.9}
    (package / "metrics.json").write_text(json.dumps(metrics, sort_keys=True) + "\n")
    lock = Path("requirements.lock")
    manifest = {
        "schema_version": "1.0.0",
        "model_version": "fixture-v1",
        "registered_model_name": "house-price-regressor",
        "mlflow_model_version": "1",
        "mlflow_run_id": "fixture-mlflow-run",
        "training_run_id": "00000000-0000-4000-8000-000000000001",
        "candidate_family": "linear",
        "dataset": {
            "name": "california_housing",
            "version": "fixture-dataset-v1",
            "sha256": "a" * 64,
            "row_count": 20640,
            "schema_version": "1.0.0",
        },
        "model_checksum": digest(model_path),
        "dependency_lock_checksum": digest(lock),
        "training_environment_version": "fixture-trainer-v1",
        "metrics": metrics,
        "signature": {
            "inputs": [{"name": name, "type": "double"} for name in FEATURE_NAMES],
            "output": "double",
        },
        "artifacts": {"model_path": "model", "metrics_path": "metrics.json", "plots": []},
        "promoted_at": datetime(2026, 10, 24, tzinfo=UTC).isoformat(),
        "previous_model_version": None,
    }
    manifest_path = package / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    pointer = {
        "schema_version": "1.0.0",
        "model_version": "fixture-v1",
        "manifest_path": "models/fixture-v1/manifest.json",
        "manifest_sha256": digest(manifest_path),
        "updated_at": datetime(2026, 10, 24, tzinfo=UTC).isoformat(),
    }
    (root / "current.json").write_text(json.dumps(pointer, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    build(Path("tests/fixtures/model-registry"))

