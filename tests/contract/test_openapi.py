from pathlib import Path

import yaml

from house_price.api.app import create_app


def test_versioned_openapi_contract_has_required_responses(project_root: Path) -> None:
    contract = yaml.safe_load(
        (project_root / "specs/001-train-container-metrics/contracts/openapi.yaml").read_text()
    )
    assert contract["openapi"] == "3.1.0"
    schemas = contract["components"]["schemas"]
    for name in ("ReadinessResponse", "ModelInfo", "PredictionResponse"):
        assert "environment_version" in schemas[name]["required"]
        assert schemas[name]["additionalProperties"] is False
    responses = contract["paths"]["/v1/predictions"]["post"]["responses"]
    assert set(responses) == {"200", "422", "500", "503"}


def test_generated_api_exposes_all_versioned_paths(tmp_path: Path) -> None:
    generated = create_app(model_registry_path=tmp_path).openapi()
    assert set(generated["paths"]) == {
        "/health/live",
        "/health/ready",
        "/v1/model",
        "/v1/predictions",
    }

