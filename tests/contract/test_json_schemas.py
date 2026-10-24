import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


def test_both_versioned_json_schemas_are_valid(project_root: Path) -> None:
    contracts = project_root / "specs/001-train-container-metrics/contracts"
    for name in ("champion-manifest.schema.json", "weekly-evidence.schema.json"):
        schema = json.loads((contracts / name).read_text())
        Draft202012Validator.check_schema(schema)


def test_fixture_champion_and_weekly_evidence_validate(project_root: Path) -> None:
    contracts = project_root / "specs/001-train-container-metrics/contracts"
    champion_schema = json.loads((contracts / "champion-manifest.schema.json").read_text())
    champion = json.loads(
        (project_root / "tests/fixtures/model-registry/models/fixture-v1/manifest.json").read_text()
    )
    Draft202012Validator(champion_schema, format_checker=FormatChecker()).validate(champion)
    weekly_schema = json.loads((contracts / "weekly-evidence.schema.json").read_text())
    evidence = {
        "schema_version": "1.0.0",
        "workflow_run_id": "fixture-workflow-1",
        "training_run_id": "00000000-0000-4000-8000-000000000001",
        "previous_model_version": None,
        "candidate_model_version": "fixture-v1",
        "effective_model_version": "fixture-v1",
        "deployment_health": "passed",
        "rollback_result": "not_required",
        "artifact_checksums": {"model": "a" * 64},
        "completed_at": "2026-10-24T12:00:00Z",
    }
    Draft202012Validator(weekly_schema, format_checker=FormatChecker()).validate(evidence)

