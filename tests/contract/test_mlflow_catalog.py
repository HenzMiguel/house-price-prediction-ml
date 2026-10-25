from types import SimpleNamespace

import pytest

from house_price.tracking.mlflow_client import (
    CATALOG_TAGS,
    DuplicateModelIdentityError,
    TrackingClient,
)


def test_required_catalog_tags_are_complete() -> None:
    assert CATALOG_TAGS == {
        "catalog.schema_version",
        "catalog.model_version",
        "catalog.manifest_sha256",
        "catalog.model_sha256",
        "catalog.training_run_id",
        "catalog.dataset_sha256",
        "catalog.origin",
        "catalog.integrity",
        "catalog.publication_state",
    }


def test_identity_lookup_rejects_duplicates(monkeypatch) -> None:
    client = object.__new__(TrackingClient)
    client.registered_model_name = "house-price-regressor"
    client.client = SimpleNamespace(
        search_model_versions=lambda *_args, **_kwargs: [
            SimpleNamespace(version="1", tags={"catalog.model_version": "v2"}),
            SimpleNamespace(version="2", tags={"catalog.model_version": "v2"}),
        ]
    )
    with pytest.raises(DuplicateModelIdentityError):
        client.find_model_version("v2")


def test_proxy_artifact_location_is_required() -> None:
    assert TrackingClient.validate_artifact_location("mlflow-artifacts:/1") == "mlflow-artifacts:/1"
    for location in ("file:///tmp/mlruns", "/mlflow-artifacts", "relative/path"):
        with pytest.raises(ValueError, match="mlflow-artifacts"):
            TrackingClient.validate_artifact_location(location)
