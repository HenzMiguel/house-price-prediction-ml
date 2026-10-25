import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError


def _validator(project_root: Path, name: str) -> Draft202012Validator:
    path = project_root / "specs/002-persist-model-mlflow/contracts" / name
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _manifest() -> dict[str, object]:
    return {
        "schema_version": "2.0.0",
        "model_version": "model-v2",
        "registered_model_name": "house-price-regressor",
        "training_run_id": str(uuid4()),
        "source_mlflow_run_id": "run-1",
        "source_mlflow_model_version": None,
        "candidate_family": "ridge",
        "code_revision": "abc123",
        "training_environment_version": "image@sha256:abc",
        "dataset": {
            "name": "california_housing",
            "version": "v1",
            "sha256": "a" * 64,
            "row_count": 20640,
            "schema_version": "1.0.0",
        },
        "parameters": {"alpha": 1.0},
        "metrics": {"mae": 0.1, "mse": 0.02, "rmse": 0.14, "r2": 0.9},
        "signature": {
            "inputs": [
                {"name": name, "type": "double"}
                for name in (
                    "MedInc",
                    "HouseAge",
                    "AveRooms",
                    "AveBedrms",
                    "Population",
                    "AveOccup",
                    "Latitude",
                    "Longitude",
                )
            ],
            "output": "double",
        },
        "artifacts": {
            "model_format": "mlflow",
            "model_path": "model",
            "parameters_path": "parameters.json",
            "metrics_path": "metrics.json",
            "dependency_lock_path": "requirements.lock",
            "plots": [],
            "checksums": {
                "model/MLmodel": "b" * 64,
                "model/model.joblib": "c" * 64,
                "parameters.json": "d" * 64,
                "metrics.json": "e" * 64,
                "requirements.lock": "f" * 64,
            },
        },
        "promoted_at": "2026-10-25T12:00:00Z",
        "previous_model_version": None,
    }


def test_feature_002_schemas_and_examples_validate(project_root: Path) -> None:
    _validator(project_root, "model-package-manifest-v2.schema.json").validate(_manifest())
    reconciliation = {
        "schema_version": "1.0.0",
        "reconciliation_id": str(uuid4()),
        "trigger": "manual",
        "mode": "check",
        "scan_fingerprint": "a" * 64,
        "started_at": "2026-10-25T12:00:00Z",
        "completed_at": "2026-10-25T12:00:01Z",
        "status": "succeeded",
        "retryable": False,
        "counts": {"scanned": 0, "registered": 0, "recovered": 0, "quarantined": 0, "unchanged": 0},
        "items": [],
    }
    _validator(project_root, "reconciliation-report.schema.json").validate(reconciliation)
    deletion = {
        "schema_version": "1.0.0",
        "deletion_id": str(uuid4()),
        "model_version": "model-v2",
        "allowed": True,
        "reason_codes": [],
        "is_pointer_target": False,
        "has_champion_alias": False,
        "is_last_integral_model": False,
        "mutation_active": False,
        "package_relpath": "models/model-v2",
        "mlflow_run_id": "run-1",
        "mlflow_model_version": "1",
        "shared_artifact_references": 0,
        "confirmation_token": "model-v2",
        "created_at": "2026-10-25T12:00:00Z",
    }
    _validator(project_root, "deletion-impact.schema.json").validate(deletion)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(schema_version="1.0.0"), "2.0.0"),
        (lambda value: value.update(model_version="../escape"), "does not match"),
        (lambda value: value["metrics"].update(mae=-1), "minimum"),
        (lambda value: value.update(secret="leak"), "Additional properties"),
    ],
)
def test_manifest_schema_rejects_invalid_examples(project_root, mutation, message) -> None:
    manifest = _manifest()
    mutation(manifest)
    with pytest.raises(ValidationError, match=message):
        _validator(project_root, "model-package-manifest-v2.schema.json").validate(manifest)
