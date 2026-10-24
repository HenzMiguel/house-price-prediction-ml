import importlib.util
from pathlib import Path


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tables_constraints_and_idempotent_upserts(project_root: Path) -> None:
    migration = load_module(
        project_root / "migrations/versions/001_observability_tables.py", "tables_migration"
    )
    sql = migration.UP_SQL
    for table in (
        "training_runs",
        "model_metrics",
        "optimization_trials",
        "artifact_plots",
        "inference_metrics",
    ):
        assert f"observability.{table}" in sql
    assert "request_count" in sql and "latency_p99_ms" in sql
    repository = (project_root / "src/house_price/tracking/observability.py").read_text()
    assert repository.count("ON CONFLICT") >= 3


def test_five_views_and_reader_permissions(project_root: Path) -> None:
    migration = load_module(
        project_root / "migrations/versions/002_grafana_views.py", "views_migration"
    )
    assert len(migration.VIEW_NAMES) == 5
    assert all(f"observability.{name}" in migration.UP_SQL for name in migration.VIEW_NAMES)
    assert "GRANT SELECT" in migration.UP_SQL
    assert "REVOKE ALL ON ALL TABLES" in migration.UP_SQL


def test_fixture_contains_five_runs_five_candidates_and_inference(project_root: Path) -> None:
    fixture = (project_root / "tests/fixtures/observability_runs.sql").read_text()
    assert fixture.count("generate_series(1, 5)") == 2
    assert "random_forest" in fixture
    assert "inference_metrics" in fixture

