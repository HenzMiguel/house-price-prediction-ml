import json

import pytest

from house_price.catalog import cli


def test_cli_defaults_are_read_only() -> None:
    assert cli.parser().parse_args(["verify"]).command == "verify"
    reconcile = cli.parser().parse_args(["reconcile"])
    assert reconcile.mode == "check"
    delete = cli.parser().parse_args(["delete", "--model-version", "v2"])
    assert delete.apply is False


def test_cli_rejects_unsupported_champion_authority() -> None:
    with pytest.raises(SystemExit):
        cli.parser().parse_args(
            ["resolve-champion", "--prefer", "mlflow", "--apply", "--confirm", "v2"]
        )


def test_json_lines_redacts_secrets_and_host_paths(capsys) -> None:
    cli.emit_event(
        "catalog_operation_completed",
        operation_id="operation-1",
        status="failed",
        diagnostic="postgresql://user:password@db/name /home/user/private",
    )
    payload = json.loads(capsys.readouterr().out)
    rendered = json.dumps(payload)
    assert "password" not in rendered
    assert "/home/user" not in rendered


@pytest.mark.parametrize("code", [0, 2, 3, 4, 5, 6, 7, 8, 130])
def test_contract_exit_codes_are_stable(code: int) -> None:
    assert code in cli.EXIT_CODES
