from pathlib import Path

import httpx2
import pytest

from house_price.api.app import create_app


@pytest.mark.anyio
async def test_inference_serves_local_champion_without_catalog_dependencies(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://invalid:invalid@127.0.0.1:1/db")
    app = create_app(
        model_registry_path=project_root / "tests/fixtures/model-registry",
        environment_version="offline-catalog",
        heartbeat_seconds=3600,
    )
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://test"
        ) as client:
            ready = await client.get("/health/ready")
            model = await client.get("/v1/model")
    assert ready.status_code == model.status_code == 200
    assert model.json()["model_version"] == "fixture-v1"
