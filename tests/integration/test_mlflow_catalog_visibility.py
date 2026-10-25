from pathlib import Path
from tempfile import TemporaryDirectory

import mlflow
import mlflow.sklearn
import numpy as np
from sklearn.linear_model import LinearRegression

from house_price.tracking.mlflow_client import CATALOG_TAGS, TrackingClient


def test_catalog_model_version_is_visible_with_lineage_and_alias(tmp_path: Path) -> None:
    client = TrackingClient(f"sqlite:///{tmp_path / 'mlflow.db'}", "catalog-visibility")
    estimator = LinearRegression().fit(np.ones((4, 8)), np.arange(4))
    with client.run(
        run_name="catalog-run",
        tags={"dataset_version": "v1", "code_revision": "abc123"},
    ) as active:
        mlflow.log_params({"family": "linear"})
        mlflow.log_metrics({"mae": 0.1, "mse": 0.01, "rmse": 0.1, "r2": 0.9})
        with TemporaryDirectory(prefix="visibility-model-") as temporary:
            model_path = Path(temporary) / "model"
            mlflow.sklearn.save_model(estimator, path=str(model_path))
            mlflow.log_artifacts(str(model_path), artifact_path="model")
        run_id = active.info.run_id
    tags = {
        "catalog.schema_version": "2.0.0",
        "catalog.model_version": "catalog-v2",
        "catalog.manifest_sha256": "a" * 64,
        "catalog.model_sha256": "b" * 64,
        "catalog.training_run_id": "00000000-0000-4000-8000-000000000001",
        "catalog.dataset_sha256": "c" * 64,
        "catalog.origin": "training",
        "catalog.integrity": "verified",
        "catalog.publication_state": "approved",
    }
    version = client.register_model_version(
        model_uri=f"runs:/{run_id}/model",
        run_id=run_id,
        model_version="catalog-v2",
        tags=tags,
    )
    client.set_champion(version)
    visible = client.client.get_model_version(client.registered_model_name, version)
    run = client.client.get_run(run_id)
    assert CATALOG_TAGS.issubset(visible.tags)
    assert client.get_champion_version() == version
    assert run.data.params["family"] == "linear"
    assert set(run.data.metrics) == {"mae", "mse", "rmse", "r2"}
    assert any(item.path == "model" for item in client.client.list_artifacts(run_id))
