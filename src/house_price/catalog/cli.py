"""Operational model-catalog CLI with stable JSON Lines output and exit codes."""

import argparse
import json
import re
import signal
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import ValidationError

from house_price.catalog import CatalogError
from house_price.catalog.repository import CatalogRepository
from house_price.settings import Settings
from house_price.tracking.mlflow_client import TrackingClient

EXIT_CODES = frozenset({0, 2, 3, 4, 5, 6, 7, 8, 130})
_URI_RE = re.compile(r"(?:postgresql(?:\+psycopg)?|https?)://\S+", re.IGNORECASE)
_HOST_PATH_RE = re.compile(r"/(?:home|Users|root|var/lib)/[^\s\"']+")
_SECRET_RE = re.compile(
    r"(?i)(?:password|passwd|token|secret|api[_-]?key)(?:\s*[:=]\s*|[^\s]{0,3})[^\s,;]+"
)


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, UUID)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, Path):
        return value.name
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if not isinstance(value, str):
        return value
    rendered = _URI_RE.sub("[redacted-uri]", value)
    rendered = _HOST_PATH_RE.sub("[redacted-path]", rendered)
    rendered = _SECRET_RE.sub("[redacted-secret]", rendered)
    return rendered


def emit_event(event: str, *, operation_id: str, **values: Any) -> None:
    payload = {
        "event": event,
        "operation_id": operation_id,
        "timestamp": datetime.now(UTC),
        **redact(values),
    }
    print(json.dumps(payload, default=_json_default, sort_keys=True), flush=True)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(prog="model-catalog")
    subcommands = command.add_subparsers(dest="command", required=True)

    verify = subcommands.add_parser("verify")
    verify.add_argument("--model-version")
    verify.add_argument("--probe-artifacts", action="store_true")
    verify.add_argument("--json", action="store_true")

    reconcile = subcommands.add_parser("reconcile")
    reconcile.add_argument("--mode", choices=("check", "apply"), default="check")
    reconcile.add_argument(
        "--trigger", choices=("manual", "startup", "weekly", "restore"), default="manual"
    )
    reconcile.add_argument("--model-version")
    reconcile.add_argument("--json", action="store_true")

    listing = subcommands.add_parser("list")
    listing.add_argument("--integrity")
    listing.add_argument("--lifecycle")
    listing.add_argument("--json", action="store_true")

    resolve = subcommands.add_parser("resolve-champion")
    resolve.add_argument("--prefer", choices=("volume",), required=True)
    resolve.add_argument("--apply", action="store_true", required=True)
    resolve.add_argument("--confirm", required=True)
    resolve.add_argument("--json", action="store_true")

    delete = subcommands.add_parser("delete")
    delete.add_argument("--model-version", required=True)
    delete.add_argument("--apply", action="store_true")
    delete.add_argument("--confirm")
    delete.add_argument("--json", action="store_true")

    purge = subcommands.add_parser("purge")
    purge.add_argument("--deletion-id", required=True)
    purge.add_argument("--apply", action="store_true", required=True)
    purge.add_argument("--confirm", required=True)
    purge.add_argument("--json", action="store_true")
    return command


def _dependencies() -> tuple[Settings, CatalogRepository, TrackingClient]:
    settings = Settings()  # type: ignore[call-arg]
    repository = CatalogRepository(
        settings.database_url, advisory_lock_id=settings.catalog_advisory_lock_id
    )
    tracking = TrackingClient(
        settings.mlflow_tracking_uri,
        settings.mlflow_experiment_name,
        recovery_experiment_name=settings.mlflow_recovery_experiment_name,
        registered_model_name=settings.mlflow_registered_model_name,
        champion_alias=settings.mlflow_champion_alias,
    )
    return settings, repository, tracking


def _run(args: argparse.Namespace, operation_id: str) -> tuple[int, dict[str, Any]]:
    settings, repository, tracking = _dependencies()
    if args.command == "list":
        entries = repository.list_model_entries(integrity=args.integrity, lifecycle=args.lifecycle)
        return 0, {
            "status": "succeeded",
            "count": len(entries),
            "items": [
                {
                    "model_version": entry.model_version,
                    "integrity_status": entry.integrity_status.value,
                    "catalog_status": entry.catalog_status.value,
                    "lifecycle_status": entry.lifecycle_status.value,
                    "promotion_status": entry.promotion_status.value,
                    "manifest_sha256": entry.manifest_sha256[:12],
                    "model_sha256": entry.model_sha256[:12],
                    "mlflow_run_id": entry.active_mlflow_run_id,
                    "mlflow_model_version": entry.active_mlflow_model_version,
                }
                for entry in entries
            ],
        }

    if args.command in {"verify", "reconcile", "resolve-champion"}:
        from house_price.catalog.reconciliation import CatalogReconciler

        service = CatalogReconciler(
            settings.model_registry_path, repository=repository, tracking=tracking
        )
        if args.command == "verify":
            result = service.verify(
                model_version=args.model_version, probe_artifacts=args.probe_artifacts
            )
        elif args.command == "reconcile":
            result = service.reconcile(
                mode=args.mode,
                trigger=args.trigger,
                model_version=args.model_version,
            )
        else:
            result = service.resolve_champion(args.confirm)
        status = result.get("status", "succeeded")
        return (3 if status == "partial" else 0), result

    from house_price.catalog.removal import CatalogRemoval

    removal = CatalogRemoval(settings.model_registry_path, repository, tracking)
    if args.command == "delete":
        result = removal.delete(args.model_version, apply=args.apply, confirmation=args.confirm)
    else:
        result = removal.purge(UUID(args.deletion_id), apply=args.apply, confirmation=args.confirm)
    return 0, result


def main(argv: Sequence[str] | None = None) -> int:
    operation_id = str(uuid4())
    signal.signal(signal.SIGTERM, lambda *_args: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        args = parser().parse_args(argv)
        code, result = _run(args, operation_id)
        emit_event(
            "catalog_operation_completed",
            operation_id=operation_id,
            command=args.command,
            **result,
        )
        return code
    except KeyboardInterrupt:
        emit_event(
            "catalog_operation_completed",
            operation_id=operation_id,
            status="interrupted",
            retryable=True,
        )
        return 130
    except (ValidationError, ValueError, argparse.ArgumentError) as exc:
        emit_event(
            "catalog_operation_completed",
            operation_id=operation_id,
            status="invalid",
            retryable=False,
            reason_code="configuration_invalid",
            diagnostic=str(exc),
        )
        return 2
    except CatalogError as exc:
        emit_event(
            "catalog_operation_completed",
            operation_id=operation_id,
            status="failed",
            retryable=exc.retryable,
            reason_code=type(exc).__name__.lower(),
            diagnostic=str(exc),
        )
        return exc.exit_code
    except (ConnectionError, TimeoutError) as exc:
        emit_event(
            "catalog_operation_completed",
            operation_id=operation_id,
            status="failed",
            retryable=True,
            reason_code="dependency_unavailable",
            diagnostic=str(exc),
        )
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
