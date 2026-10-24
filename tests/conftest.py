from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def dataset_paths(project_root: Path) -> tuple[Path, Path]:
    return (
        project_root / "data/california_housing.parquet",
        project_root / "data/dataset-manifest.json",
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"

