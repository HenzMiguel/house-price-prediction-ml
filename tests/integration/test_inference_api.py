from pathlib import Path

import httpx2
import pytest

from house_price.api.app import create_app

VALID = {
    "MedInc": 8.3252,
    "HouseAge": 41,
    "AveRooms": 6.9841,
    "AveBedrms": 1.0238,
    "Population": 322,
    "AveOccup": 2.5556,
    "Latitude": 37.88,
    "Longitude": -122.23,
}


@pytest.mark.anyio
async def test_liveness_and_not_ready_without_champion(tmp_path: Path) -> None:
    app = create_app(model_registry_path=tmp_path)
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/health/live")).status_code == 200
            response = await client.get("/health/ready")
        assert response.status_code == 503
        assert set(response.json()) == {"code", "message", "request_id"}


@pytest.mark.anyio
async def test_ready_model_and_prediction_share_versions(project_root: Path) -> None:
    root = project_root / "tests/fixtures/model-registry"
    app = create_app(model_registry_path=root, environment_version="inference-fixture-v1")
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://test"
        ) as client:
            ready = await client.get("/health/ready")
            model = await client.get("/v1/model")
            prediction = await client.post("/v1/predictions", json={"instances": [VALID]})
        assert ready.status_code == model.status_code == prediction.status_code == 200
        assert ready.json()["environment_version"] == "inference-fixture-v1"
        assert model.json()["environment_version"] == "inference-fixture-v1"
        assert prediction.json()["environment_version"] == "inference-fixture-v1"
        assert ready.json()["model_version"] == model.json()["model_version"]
        assert model.json()["model_version"] == prediction.json()["model_version"]
        assert len(prediction.json()["predictions"]) == 1


@pytest.mark.anyio
async def test_invalid_payload_returns_contract_error(project_root: Path) -> None:
    root = project_root / "tests/fixtures/model-registry"
    app = create_app(model_registry_path=root)
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/predictions", json={"instances": [{**VALID, "extra": 1}]}
            )
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"
        assert response.json()["issues"]

