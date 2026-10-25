"""Safe catalog verification and reconciliation without model deserialization."""

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from house_price.catalog import CatalogLockUnavailable, CatalogProtectedOperationError
from house_price.catalog.models import (
    CatalogStatus,
    IntegrityStatus,
    LifecycleStatus,
    ModelEntry,
    OperationEvent,
    PromotionStatus,
    ReconciliationItem,
    ReconciliationRun,
)
from house_price.catalog.repository import CatalogRepository
from house_price.registry.atomic import fsync_directory, sha256_file
from house_price.registry.manifest import (
    ChampionManifest,
    LegacyModelManifestV1,
    PersistedModelManifestV2,
    validate_package,
)
from house_price.registry.pointer import read_pointer
from house_price.tracking.mlflow_client import TrackingClient


@dataclass(frozen=True)
class ScannedPackage:
    path: Path
    relpath: str
    model_version: str | None
    manifest: ChampionManifest | None
    manifest_sha256: str | None
    error: str | None = None


def scan_fingerprint(packages: list[ScannedPackage]) -> str:
    digest = hashlib.sha256()
    for package in packages:
        digest.update(package.relpath.encode())
        digest.update(b"\0")
        digest.update((package.manifest_sha256 or package.error or "unreadable").encode())
        digest.update(b"\n")
    return digest.hexdigest()


class CatalogReconciler:
    def __init__(
        self,
        root: Path,
        *,
        repository: CatalogRepository,
        tracking: TrackingClient,
        minimum_free_bytes: int = 10 * 1024 * 1024,
        expected_uid: int | None = None,
    ) -> None:
        self.root = root
        self.repository = repository
        self.tracking = tracking
        self.minimum_free_bytes = minimum_free_bytes
        self.expected_uid = os.geteuid() if expected_uid is None else expected_uid

    def preflight(self, *, probe_artifacts: bool = False) -> dict[str, Any]:
        if not self.root.is_dir():
            raise OSError("model registry is unavailable or is not a directory")
        if self.root.stat().st_uid != self.expected_uid:
            raise PermissionError("model registry is owned by an incompatible UID")
        usage = shutil.disk_usage(self.root)
        if usage.free < self.minimum_free_bytes:
            raise OSError("model registry has insufficient free space")
        token = uuid4().hex
        source = self.root / f".catalog-probe-{token}.tmp"
        destination = self.root / f".catalog-probe-{token}.renamed"
        descriptor = -1
        try:
            descriptor = os.open(source, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(descriptor, b"catalog-probe\n")
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(source, destination)
            fsync_directory(self.root)
            if destination.read_bytes() != b"catalog-probe\n":
                raise OSError("model registry probe readback failed")
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            source.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
        server_version = self.tracking.assert_server_version()
        artifact_location = self.tracking.active_artifact_location()
        if probe_artifacts:
            self.tracking.probe_artifacts()
        return {
            "status": "succeeded",
            "server_version": server_version,
            "artifact_location": artifact_location,
            "free_bytes": usage.free,
        }

    def verify(
        self, *, model_version: str | None = None, probe_artifacts: bool = False
    ) -> dict[str, Any]:
        preflight = self.preflight(probe_artifacts=probe_artifacts)
        scanned = self.scan(model_version=model_version)
        items: list[dict[str, Any]] = []
        pointer = None
        pointer_error = None
        try:
            pointer = read_pointer(self.root)
        except (OSError, ValueError):
            pointer_error = "pointer_invalid"
        alias = self.tracking.get_champion_version()
        for package in scanned:
            reasons: list[str] = []
            if package.error or package.manifest is None or package.model_version is None:
                reasons.append(package.error or "manifest_invalid")
            else:
                manifest = package.manifest
                entry = self.repository.get_model_entry(package.model_version)
                if entry is None:
                    reasons.append("ledger_entry_missing")
                else:
                    if (
                        entry.manifest_sha256 != package.manifest_sha256
                        or entry.model_sha256 != manifest.model_checksum
                        or entry.package_relpath != package.relpath
                    ):
                        reasons.append("ledger_package_mismatch")
                    version = self.tracking.find_model_version(package.model_version)
                    if version is None:
                        reasons.append("mlflow_version_missing")
                    else:
                        tags = getattr(version, "tags", None) or {}
                        expected_tags = {
                            "catalog.model_version": package.model_version,
                            "catalog.manifest_sha256": package.manifest_sha256,
                            "catalog.model_sha256": manifest.model_checksum,
                            "catalog.integrity": "verified",
                        }
                        if any(tags.get(key) != value for key, value in expected_tags.items()):
                            reasons.append("mlflow_tags_mismatch")
                        if entry.active_mlflow_model_version != str(version.version):
                            reasons.append("mlflow_link_mismatch")
                    if (
                        not entry.active_mlflow_run_id
                        or self.tracking.get_run(entry.active_mlflow_run_id) is None
                    ):
                        reasons.append("mlflow_run_missing")
                    elif entry.active_mlflow_model_version:
                        with tempfile.TemporaryDirectory(
                            prefix="catalog-verify-artifact-"
                        ) as temporary:
                            try:
                                remote = self.tracking.download_artifacts(
                                    entry.active_mlflow_run_id,
                                    "metadata/manifest.json",
                                    Path(temporary),
                                )
                                if sha256_file(remote) != package.manifest_sha256:
                                    reasons.append("mlflow_artifact_checksum_mismatch")
                            except (OSError, RuntimeError):
                                reasons.append("mlflow_artifact_unavailable")
                    if entry.promotion_status.value == "champion":
                        if pointer is None or pointer.model_version != package.model_version:
                            reasons.append(pointer_error or "pointer_divergence")
                        if alias != entry.active_mlflow_model_version:
                            reasons.append("alias_divergence")
            items.append(
                {
                    "package_relpath": package.relpath,
                    "model_version": package.model_version,
                    "status": "invalid" if reasons else "verified",
                    "reason_codes": sorted(set(reasons)),
                }
            )
        if pointer and not any(item["model_version"] == pointer.model_version for item in items):
            items.append(
                {
                    "package_relpath": f"models/{pointer.model_version}",
                    "model_version": pointer.model_version,
                    "status": "invalid",
                    "reason_codes": ["pointer_target_missing"],
                }
            )
        status = "partial" if any(item["status"] != "verified" for item in items) else "succeeded"
        return {
            **preflight,
            "status": status,
            "model_version": model_version,
            "counts": {
                "scanned": len(items),
                "verified": sum(item["status"] == "verified" for item in items),
                "invalid": sum(item["status"] != "verified" for item in items),
            },
            "items": items,
        }

    def scan(self, *, model_version: str | None = None) -> list[ScannedPackage]:
        models = self.root / "models"
        if not models.exists():
            return []
        if not models.is_dir() or models.is_symlink():
            raise ValueError("models path must be a real directory")
        results: list[ScannedPackage] = []
        for path in sorted(models.iterdir(), key=lambda item: item.name):
            if model_version and path.name != model_version:
                continue
            relpath = f"models/{path.name}"
            if path.is_symlink() or not path.is_dir():
                results.append(
                    ScannedPackage(path, relpath, path.name, None, None, "unsafe_package_path")
                )
                continue
            try:
                manifest = validate_package(path, require_directory_identity=True)
                results.append(
                    ScannedPackage(
                        path,
                        relpath,
                        manifest.model_version,
                        manifest,
                        sha256_file(path / "manifest.json"),
                    )
                )
            except (OSError, ValueError):
                results.append(
                    ScannedPackage(
                        path,
                        relpath,
                        path.name,
                        None,
                        None,
                        "package_invalid",
                    )
                )
        return results

    def reconcile(
        self,
        *,
        mode: str = "check",
        trigger: str = "manual",
        model_version: str | None = None,
    ) -> dict[str, Any]:
        if mode not in {"check", "apply"}:
            raise ValueError("reconciliation mode must be check or apply")
        if trigger not in {"manual", "startup", "weekly", "restore"}:
            raise ValueError("unsupported reconciliation trigger")
        packages = self.scan(model_version=model_version)
        fingerprint = scan_fingerprint(packages)
        reconciliation_id = uuid4()
        started = datetime.now(UTC)
        if mode == "check":
            items = [self._check_item(package) for package in packages]
            return self._report(
                reconciliation_id,
                trigger,
                mode,
                fingerprint,
                started,
                items,
            )
        try:
            with self.repository.mutation_lock() as connection:
                items = [
                    self._apply_item(
                        package,
                        reconciliation_id=reconciliation_id,
                        connection=connection,
                    )
                    for package in packages
                ]
                report = self._report(
                    reconciliation_id,
                    trigger,
                    mode,
                    fingerprint,
                    started,
                    items,
                )
                run = ReconciliationRun(
                    reconciliation_id=reconciliation_id,
                    trigger=trigger,
                    mode=mode,
                    scan_fingerprint=fingerprint,
                    status=report["status"],
                    started_at=started,
                    completed_at=datetime.fromisoformat(
                        report["completed_at"].replace("Z", "+00:00")
                    ),
                    scanned_count=report["counts"]["scanned"],
                    registered_count=report["counts"]["registered"],
                    recovered_count=report["counts"]["recovered"],
                    quarantined_count=report["counts"]["quarantined"],
                    unchanged_count=report["counts"]["unchanged"],
                    items=items,
                )
                self.repository.save_reconciliation(run, connection=connection)
                return report
        except CatalogLockUnavailable:
            completed = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            return {
                "schema_version": "1.0.0",
                "reconciliation_id": str(reconciliation_id),
                "trigger": trigger,
                "mode": mode,
                "scan_fingerprint": fingerprint,
                "started_at": started.isoformat().replace("+00:00", "Z"),
                "completed_at": completed,
                "status": "lock_unavailable",
                "retryable": True,
                "counts": {
                    "scanned": 0,
                    "registered": 0,
                    "recovered": 0,
                    "quarantined": 0,
                    "unchanged": 0,
                },
                "items": [],
            }

    def resolve_champion(self, model_version: str) -> dict[str, Any]:
        pointer = read_pointer(self.root)
        if pointer is None or pointer.model_version != model_version:
            raise CatalogProtectedOperationError(
                "resolution may only prefer the package currently served by current.json"
            )
        package = self.root / pointer.manifest_path
        validate_package(package.parent, require_directory_identity=True)
        if sha256_file(package) != pointer.manifest_sha256:
            raise CatalogProtectedOperationError("served package manifest checksum is invalid")
        with self.repository.mutation_lock() as connection:
            entry = self.repository.get_model_entry(model_version, connection=connection)
            if entry is None or not entry.promotable or not entry.active_mlflow_model_version:
                raise CatalogProtectedOperationError(
                    "served package is not verified and registered"
                )
            version = self.tracking.find_model_version(model_version)
            if version is None or str(version.version) != entry.active_mlflow_model_version:
                raise CatalogProtectedOperationError("MLflow version does not match served package")
            previous = self.tracking.get_champion_version()
            self.tracking.set_champion(entry.active_mlflow_model_version)
            for candidate in self.repository.list_model_entries():
                if candidate.promotion_status is PromotionStatus.CHAMPION and (
                    candidate.model_version != model_version
                ):
                    self.repository.update_model_entry(
                        candidate.model_version,
                        candidate.revision,
                        {"promotion_status": PromotionStatus.SUPERSEDED},
                        connection=connection,
                    )
            if entry.promotion_status is not PromotionStatus.CHAMPION:
                self.repository.update_model_entry(
                    model_version,
                    entry.revision,
                    {"promotion_status": PromotionStatus.CHAMPION},
                    connection=connection,
                )
            self.repository.append_event(
                OperationEvent(
                    event_id=uuid4(),
                    operation_id=uuid4(),
                    operation="resolve_champion",
                    model_version=model_version,
                    from_state={"alias": previous},
                    to_state={"alias": entry.active_mlflow_model_version},
                    phase="alias_repaired_to_volume",
                    result="succeeded",
                    occurred_at=datetime.now(UTC),
                ),
                connection=connection,
            )
        return {
            "status": "succeeded",
            "model_version": model_version,
            "mlflow_model_version": entry.active_mlflow_model_version,
        }

    def _check_item(self, package: ScannedPackage) -> ReconciliationItem:
        now = datetime.now(UTC)
        if package.error or package.manifest is None or package.model_version is None:
            return ReconciliationItem(
                package_relpath=package.relpath,
                model_version=package.model_version,
                manifest_sha256=package.manifest_sha256,
                action="quarantined",
                result="failed",
                reason_code=package.error or "manifest_invalid",
                occurred_at=now,
            )
        if self.repository.tombstone_exists(package.model_version):
            return ReconciliationItem(
                package_relpath=package.relpath,
                model_version=package.model_version,
                manifest_sha256=package.manifest_sha256,
                action="conflict",
                result="skipped",
                reason_code="tombstoned_package",
                occurred_at=now,
            )
        entry = self.repository.get_model_entry(package.model_version)
        version = self.tracking.find_model_version(package.model_version)
        if entry and version:
            return ReconciliationItem(
                package_relpath=package.relpath,
                model_version=package.model_version,
                manifest_sha256=package.manifest_sha256,
                action="unchanged",
                result="succeeded",
                mlflow_run_id=entry.active_mlflow_run_id,
                mlflow_model_version=entry.active_mlflow_model_version,
                occurred_at=now,
            )
        action = (
            "registered"
            if self.tracking.get_run(package.manifest.mlflow_run_id)
            else "recovered"
        )
        if isinstance(package.manifest, LegacyModelManifestV1) and action == "recovered":
            action = "quarantined"
        return ReconciliationItem(
            package_relpath=package.relpath,
            model_version=package.model_version,
            manifest_sha256=package.manifest_sha256,
            action=action,
            result="skipped",
            reason_code="apply_required" if action != "quarantined" else "legacy_source_missing",
            occurred_at=now,
        )

    def _tags(
        self,
        package: ScannedPackage,
        *,
        origin: str,
    ) -> dict[str, str]:
        assert package.manifest is not None
        assert package.manifest_sha256 is not None
        manifest = package.manifest
        return {
            "catalog.schema_version": manifest.schema_version,
            "catalog.model_version": manifest.model_version,
            "catalog.manifest_sha256": package.manifest_sha256,
            "catalog.model_sha256": manifest.model_checksum,
            "catalog.training_run_id": str(manifest.training_run_id),
            "catalog.dataset_sha256": manifest.dataset.sha256,
            "catalog.origin": origin,
            "catalog.integrity": "verified",
            "catalog.publication_state": "ready",
        }

    def _entry(
        self,
        package: ScannedPackage,
        *,
        run_id: str | None,
        version: str | None,
        integrity: IntegrityStatus = IntegrityStatus.VERIFIED,
        catalog: CatalogStatus = CatalogStatus.REGISTERED,
        lifecycle: LifecycleStatus = LifecycleStatus.ACTIVE,
        diagnostic: str | None = None,
    ) -> ModelEntry:
        assert package.manifest is not None
        assert package.manifest_sha256 is not None
        manifest = package.manifest
        return ModelEntry(
            model_version=manifest.model_version,
            manifest_schema_version=manifest.schema_version,
            manifest_sha256=package.manifest_sha256,
            model_sha256=manifest.model_checksum,
            package_relpath=package.relpath,
            training_run_id=manifest.training_run_id,
            source_mlflow_run_id=manifest.mlflow_run_id,
            source_mlflow_model_version=manifest.mlflow_model_version,
            active_mlflow_run_id=run_id,
            active_mlflow_model_version=version,
            integrity_status=integrity,
            catalog_status=catalog,
            lifecycle_status=lifecycle,
            promotion_status=PromotionStatus.CANDIDATE,
            diagnostic_code=diagnostic,
            first_seen_at=datetime.now(UTC),
            verified_at=datetime.now(UTC) if integrity is IntegrityStatus.VERIFIED else None,
            last_reconciled_at=datetime.now(UTC),
        )

    def _apply_item(
        self,
        package: ScannedPackage,
        *,
        reconciliation_id: UUID,
        connection: Any,
    ) -> ReconciliationItem:
        now = datetime.now(UTC)
        if package.error or package.manifest is None or package.model_version is None:
            return ReconciliationItem(
                package_relpath=package.relpath,
                model_version=package.model_version,
                manifest_sha256=package.manifest_sha256,
                action="quarantined",
                result="failed",
                reason_code=package.error or "manifest_invalid",
                occurred_at=now,
            )
        manifest = package.manifest
        if self.repository.tombstone_exists(manifest.model_version):
            return ReconciliationItem(
                package_relpath=package.relpath,
                model_version=manifest.model_version,
                manifest_sha256=package.manifest_sha256,
                action="conflict",
                result="skipped",
                reason_code="tombstoned_package",
                occurred_at=now,
            )
        entry = self.repository.get_model_entry(manifest.model_version, connection=connection)
        version = self.tracking.find_model_version(manifest.model_version)
        if entry and (
            entry.manifest_sha256 != package.manifest_sha256
            or entry.model_sha256 != manifest.model_checksum
        ):
            return ReconciliationItem(
                package_relpath=package.relpath,
                model_version=manifest.model_version,
                manifest_sha256=package.manifest_sha256,
                action="conflict",
                result="failed",
                reason_code="identity_checksum_conflict",
                occurred_at=now,
            )
        if entry and version and entry.active_mlflow_model_version == str(version.version):
            return ReconciliationItem(
                package_relpath=package.relpath,
                model_version=manifest.model_version,
                manifest_sha256=package.manifest_sha256,
                action="unchanged",
                result="succeeded",
                mlflow_run_id=entry.active_mlflow_run_id,
                mlflow_model_version=entry.active_mlflow_model_version,
                occurred_at=now,
            )
        source_run = self.tracking.get_run(manifest.mlflow_run_id)
        if isinstance(manifest, LegacyModelManifestV1) and source_run is None:
            unsupported = self._entry(
                package,
                run_id=None,
                version=None,
                integrity=IntegrityStatus.UNSUPPORTED,
                catalog=CatalogStatus.UNREGISTERED,
                lifecycle=LifecycleStatus.QUARANTINED,
                diagnostic="legacy_source_missing",
            )
            self.repository.upsert_model_entry(unsupported, connection=connection)
            return ReconciliationItem(
                package_relpath=package.relpath,
                model_version=manifest.model_version,
                manifest_sha256=package.manifest_sha256,
                action="quarantined",
                result="succeeded",
                reason_code="legacy_source_missing",
                occurred_at=now,
            )
        action = "registered"
        if version is not None:
            run_id = str(getattr(version, "run_id", None) or manifest.mlflow_run_id)
            mlflow_version = str(version.version)
        elif source_run is not None:
            run_id = manifest.mlflow_run_id
            mlflow_version = self.tracking.register_model_version(
                model_uri=f"runs:/{run_id}/model",
                run_id=run_id,
                model_version=manifest.model_version,
                tags=self._tags(package, origin="training"),
            )
        elif isinstance(manifest, PersistedModelManifestV2):
            action = "recovered"
            run_id, mlflow_version = self.tracking.recover_package(
                package.path,
                manifest,
                reconciliation_id=reconciliation_id,
                tags=self._tags(package, origin="recovery"),
            )
        else:  # pragma: no cover - exhaustive safety guard
            raise RuntimeError("unsupported reconciliation package")
        linked = self._entry(package, run_id=run_id, version=mlflow_version)
        self.repository.upsert_model_entry(linked, connection=connection)
        self.repository.append_event(
            OperationEvent(
                event_id=uuid4(),
                operation_id=reconciliation_id,
                operation="reconcile",
                model_version=manifest.model_version,
                phase=action,
                result="succeeded",
                occurred_at=now,
            ),
            connection=connection,
        )
        return ReconciliationItem(
            package_relpath=package.relpath,
            model_version=manifest.model_version,
            manifest_sha256=package.manifest_sha256,
            action=action,
            result="succeeded",
            mlflow_run_id=run_id,
            mlflow_model_version=mlflow_version,
            occurred_at=now,
        )

    @staticmethod
    def _report(
        reconciliation_id: UUID,
        trigger: str,
        mode: str,
        fingerprint: str,
        started: datetime,
        items: list[ReconciliationItem],
    ) -> dict[str, Any]:
        registered = sum(
            item.action == "registered" and item.result == "succeeded" for item in items
        )
        recovered = sum(item.action == "recovered" and item.result == "succeeded" for item in items)
        quarantined = sum(item.action in {"quarantined", "conflict"} for item in items)
        unchanged = sum(item.action == "unchanged" for item in items)
        partial = any(item.action in {"quarantined", "conflict"} for item in items)
        completed = datetime.now(UTC)
        return {
            "schema_version": "1.0.0",
            "reconciliation_id": str(reconciliation_id),
            "trigger": trigger,
            "mode": mode,
            "scan_fingerprint": fingerprint,
            "started_at": started.isoformat().replace("+00:00", "Z"),
            "completed_at": completed.isoformat().replace("+00:00", "Z"),
            "status": "partial" if partial else "succeeded",
            "retryable": False,
            "counts": {
                "scanned": len(items),
                "registered": registered,
                "recovered": recovered,
                "quarantined": quarantined,
                "unchanged": unchanged,
            },
            "items": [
                {
                    "package_relpath": item.package_relpath,
                    "model_version": item.model_version,
                    "manifest_sha256": item.manifest_sha256,
                    "action": item.action,
                    "result": item.result,
                    "reason_code": item.reason_code,
                    "mlflow_run_id": item.mlflow_run_id,
                    "mlflow_model_version": item.mlflow_model_version,
                }
                for item in items
            ],
        }
