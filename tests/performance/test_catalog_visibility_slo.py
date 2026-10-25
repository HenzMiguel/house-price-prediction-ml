import json
from time import monotonic

from house_price.catalog.cli import redact


def test_catalog_projection_and_secret_scan_complete_within_two_minutes() -> None:
    started = monotonic()
    seeded_secret = "catalog-secret-123"
    payload = {
        "tags": {"catalog.model_version": "v2", "token": seeded_secret},
        "parameters": {"password": seeded_secret},
        "diagnostic": f"postgresql://user:{seeded_secret}@db/name",
        "artifacts": [f"/home/operator/{seeded_secret}/manifest.json"],
    }
    rendered = json.dumps(redact(payload))
    assert seeded_secret not in rendered
    assert monotonic() - started < 120
