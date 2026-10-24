import os
import subprocess

import pytest


@pytest.mark.docker
@pytest.mark.skipif(
    os.getenv("RUN_DOCKER_PERSISTENCE_TEST") != "1",
    reason="set RUN_DOCKER_PERSISTENCE_TEST=1 for the stateful Compose acceptance test",
)
def test_named_volumes_survive_compose_down_up() -> None:
    commands = {
        "pointer": [
            "docker", "compose", "exec", "-T", "inference", "python", "-c",
            "import pathlib; print(pathlib.Path('/model-registry/current.json').read_text())",
        ],
        "observability": [
            "docker", "compose", "exec", "-T", "postgres", "psql", "-U", "postgres",
            "-d", "house_price", "-Atc",
            "SELECT count(*) || ':' || (SELECT count(*) FROM observability.model_metrics) "
            "FROM observability.training_runs",
        ],
        "artifacts": [
            "docker", "compose", "exec", "-T", "mlflow", "python", "-c",
            "import pathlib; p=pathlib.Path('/mlflow-artifacts'); "
            "print(sorted((str(x.relative_to(p)), x.stat().st_size) for x in p.rglob('*') "
            "if x.is_file()))",
        ],
    }
    before = {
        name: subprocess.check_output(command, text=True) for name, command in commands.items()
    }
    subprocess.run(["docker", "compose", "down"], check=True)
    subprocess.run(
        ["docker", "compose", "up", "-d", "--wait", "postgres", "mlflow", "inference"],
        check=True,
    )
    after = {
        name: subprocess.check_output(command, text=True) for name, command in commands.items()
    }
    assert after == before

