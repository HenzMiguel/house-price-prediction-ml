from time import perf_counter

import httpx2
import pytest

from house_price.api.app import create_app
from tests.integration.test_inference_api import VALID


@pytest.mark.performance
@pytest.mark.anyio
async def test_ninety_five_percent_of_predictions_finish_within_two_seconds(project_root) -> None:
    app = create_app(model_registry_path=project_root / "tests/fixtures/model-registry")
    durations = []
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://test"
        ) as client:
            for _ in range(100):
                started = perf_counter()
                response = await client.post("/v1/predictions", json={"instances": [VALID]})
                durations.append(perf_counter() - started)
                assert response.status_code == 200
    assert sum(duration <= 2 for duration in durations) >= 95

