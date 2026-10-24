from pathlib import Path

import yaml


def test_images_are_non_root_and_revisioned(project_root: Path) -> None:
    for name in ("trainer.Dockerfile", "inference.Dockerfile", "mlflow.Dockerfile"):
        content = (project_root / "docker" / name).read_text()
        assert "USER 0" not in content
        assert "USER 1000" in content
    for name in ("trainer.Dockerfile", "inference.Dockerfile"):
        content = (project_root / "docker" / name).read_text()
        assert "org.opencontainers.image.revision" in content


def test_compose_drops_capabilities_and_never_mounts_docker_socket(project_root: Path) -> None:
    raw = (project_root / "compose.yaml").read_text()
    compose = yaml.safe_load(raw)
    assert "/var/run/docker.sock" not in raw
    for service in compose["services"].values():
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert service["cap_drop"] == ["ALL"]
        assert service["deploy"]["resources"]["limits"]
    inference_volumes = compose["services"]["inference"]["volumes"]
    assert any(str(volume).endswith(":ro") for volume in inference_volumes)
    assert compose["networks"]["backend"]["internal"] is True
    assert set(compose["services"]["trainer"]["networks"]) == {"backend"}
    assert set(compose["services"]["mlflow"]["networks"]) == {"backend", "host-access"}
    assert "host-access" in compose["services"]["postgres"]["networks"]
    assert "host-access" in compose["services"]["inference"]["networks"]
    assert compose["services"]["mlflow"]["ports"][0].startswith("127.0.0.1:")
    mlflow_command = compose["services"]["mlflow"]["command"]
    assert mlflow_command[mlflow_command.index("--workers") + 1] == "1"
    assert mlflow_command[mlflow_command.index("--host") + 1] == "0.0.0.0"
    assert "mlflow:5000" in mlflow_command[mlflow_command.index("--allowed-hosts") + 1]
    assert "localhost:5000" in mlflow_command[mlflow_command.index("--allowed-hosts") + 1]
    assert "MLFLOW_DEFAULT_ARTIFACT_ROOT" not in compose["services"]["mlflow"]["environment"]


def test_no_secrets_or_dataset_payloads_are_baked_into_images(project_root: Path) -> None:
    dockerfiles = "\n".join(
        path.read_text() for path in (project_root / "docker").glob("*.Dockerfile")
    )
    assert "PASSWORD=" not in dockerfiles
    assert "AIML House price predictor.ipynb" not in dockerfiles
    trainer = (project_root / "docker/trainer.Dockerfile").read_text()
    assert "chmod -R a-w /app/data" in trainer

