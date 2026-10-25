from pathlib import Path
from types import SimpleNamespace

import pytest

from house_price.catalog.reconciliation import CatalogReconciler


class ProbeTracking:
    experiment_name = "house-price-training-v2"

    def assert_server_version(self):
        return "3.17.2"

    def active_artifact_location(self):
        return "mlflow-artifacts:/"

    def probe_artifacts(self):
        return None


class FailedProxyTracking(ProbeTracking):
    def probe_artifacts(self):
        raise ConnectionError("artifact proxy unavailable")


def service(root: Path) -> CatalogReconciler:
    return CatalogReconciler(
        root,
        repository=SimpleNamespace(),
        tracking=ProbeTracking(),
        minimum_free_bytes=1,
    )


def test_registry_preflight_round_trips_write_and_rename(tmp_path: Path) -> None:
    assert service(tmp_path).preflight(probe_artifacts=True)["status"] == "succeeded"
    assert not list(tmp_path.glob(".catalog-probe-*"))


def test_registry_preflight_rejects_missing_or_non_directory_root(tmp_path: Path) -> None:
    root = tmp_path / "file"
    root.write_text("not a directory")
    with pytest.raises(OSError):
        service(root).preflight()


def test_registry_preflight_reports_insufficient_space(tmp_path: Path) -> None:
    reconciler = service(tmp_path)
    reconciler.minimum_free_bytes = 2**80
    with pytest.raises(OSError, match="space"):
        reconciler.preflight()


def test_registry_preflight_rejects_wrong_uid(tmp_path: Path) -> None:
    reconciler = service(tmp_path)
    reconciler.expected_uid = tmp_path.stat().st_uid + 1
    with pytest.raises(PermissionError, match="UID"):
        reconciler.preflight()


def test_registry_preflight_surfaces_write_and_rename_failures(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "house_price.catalog.reconciliation.os.open",
        lambda *_a, **_k: (_ for _ in ()).throw(PermissionError("read-only")),
    )
    with pytest.raises(PermissionError, match="read-only"):
        service(tmp_path).preflight()


def test_registry_preflight_surfaces_proxy_failure(tmp_path: Path) -> None:
    reconciler = CatalogReconciler(
        tmp_path,
        repository=SimpleNamespace(),
        tracking=FailedProxyTracking(),
        minimum_free_bytes=1,
    )
    with pytest.raises(ConnectionError, match="proxy"):
        reconciler.preflight(probe_artifacts=True)
