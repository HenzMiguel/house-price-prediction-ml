"""Protected, tombstone-first model removal and separately confirmed purge."""

import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from house_price.catalog import CatalogProtectedOperationError
from house_price.catalog.models import (
    DeletionRequest,
    LifecycleStatus,
    OperationEvent,
)
from house_price.registry.atomic import fsync_directory
from house_price.registry.pointer import read_pointer


class CatalogRemoval:
    def __init__(self, root: Path, repository: Any, tracking: Any) -> None:
        self.root = root
        self.repository = repository
        self.tracking = tracking

    def impact(self, model_version: str, *, deletion_id: UUID | None = None) -> dict[str, Any]:
        entry = self.repository.get_model_entry(model_version)
        if entry is None:
            raise CatalogProtectedOperationError("model version is absent from the catalog")
        pointer = read_pointer(self.root)
        alias = self.tracking.get_champion_version()
        integral = [
            candidate
            for candidate in self.repository.list_model_entries()
            if candidate.promotable
        ]
        mutation_active = self.repository.active_mutation_exists(model_version)
        reasons: list[str] = []
        is_pointer = bool(pointer and pointer.model_version == model_version)
        has_alias = bool(
            entry.active_mlflow_model_version
            and alias == entry.active_mlflow_model_version
        )
        is_last = entry.promotable and len(integral) <= 1
        if is_pointer:
            reasons.append("pointer_target")
        if has_alias:
            reasons.append("champion_alias")
        if is_last:
            reasons.append("last_integral_model")
        if mutation_active:
            reasons.append("mutation_active")
        shared = sum(
            candidate.model_version != model_version
            and candidate.active_mlflow_run_id == entry.active_mlflow_run_id
            for candidate in self.repository.list_model_entries()
        )
        identity = deletion_id or uuid4()
        return {
            "schema_version": "1.0.0",
            "deletion_id": str(identity),
            "model_version": model_version,
            "allowed": not reasons,
            "reason_codes": sorted(reasons),
            "is_pointer_target": is_pointer,
            "has_champion_alias": has_alias,
            "is_last_integral_model": is_last,
            "mutation_active": mutation_active,
            "package_relpath": entry.package_relpath,
            "mlflow_run_id": entry.active_mlflow_run_id,
            "mlflow_model_version": entry.active_mlflow_model_version,
            "shared_artifact_references": shared,
            "confirmation_token": model_version,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }

    def delete(
        self, model_version: str, *, apply: bool = False, confirmation: str | None = None
    ) -> dict[str, Any]:
        if not apply:
            return self.impact(model_version)
        if confirmation != model_version:
            raise CatalogProtectedOperationError("confirmation must exactly match model version")
        existing = self.repository.get_active_deletion(model_version)
        if existing and existing.state == "trashed":
            return self._deletion_result(existing, idempotent=True)
        deletion_id = existing.deletion_id if existing else uuid4()
        with self.repository.mutation_lock() as connection:
            entry = self.repository.get_model_entry(model_version, connection=connection)
            if entry is None:
                raise CatalogProtectedOperationError("model version is absent from the catalog")
            impact = self.impact(model_version, deletion_id=deletion_id)
            if not impact["allowed"]:
                raise CatalogProtectedOperationError(
                    "protected deletion refused: " + ",".join(impact["reason_codes"])
                )
            now = datetime.now(UTC)
            trash_relpath = f".trash/{deletion_id}/{model_version}"
            request = DeletionRequest(
                deletion_id=deletion_id,
                model_version=model_version,
                requested_at=now,
                confirmed_at=now,
                state="confirmed",
                package_relpath=entry.package_relpath,
                trash_relpath=trash_relpath,
                impact=impact,
            )
            self.repository.save_deletion_request(request, connection=connection)
            source = self.root / entry.package_relpath
            trash = self.root / trash_relpath
            trash.parent.mkdir(parents=True, exist_ok=True)
            if source.exists():
                if source.is_symlink() or trash.exists():
                    raise CatalogProtectedOperationError("package path is unsafe or trash collides")
                os.replace(source, trash)
                fsync_directory(source.parent)
                fsync_directory(trash.parent)
            request = request.model_copy(update={"state": "trashed"})
            self.repository.save_deletion_request(request, connection=connection)
            self.repository.update_model_entry(
                model_version,
                entry.revision,
                {"lifecycle_status": LifecycleStatus.TRASHED},
                connection=connection,
            )
            self.repository.append_event(
                OperationEvent(
                    event_id=uuid4(),
                    operation_id=deletion_id,
                    operation="delete",
                    model_version=model_version,
                    from_state={"package": entry.package_relpath},
                    to_state={"package": trash_relpath},
                    phase="package_trashed",
                    result="succeeded",
                    occurred_at=now,
                ),
                connection=connection,
            )
        if entry.active_mlflow_model_version:
            self.tracking.delete_model_version(entry.active_mlflow_model_version)
        return self._deletion_result(request, idempotent=False)

    def purge(
        self, deletion_id: UUID, *, apply: bool = True, confirmation: str | None = None
    ) -> dict[str, Any]:
        if not apply or confirmation != str(deletion_id):
            raise CatalogProtectedOperationError("purge requires the exact deletion ID")
        with self.repository.mutation_lock() as connection:
            request = self.repository.get_deletion_request(deletion_id, connection=connection)
            if request is None:
                raise CatalogProtectedOperationError("deletion request does not exist")
            if request.state == "purged":
                return self._deletion_result(request, idempotent=True)
            if request.state != "trashed" or not request.trash_relpath:
                raise CatalogProtectedOperationError("only trashed packages may be purged")
            trash = self.root / request.trash_relpath
            if trash.is_symlink():
                raise CatalogProtectedOperationError("trash path is unsafe")
            if trash.exists():
                shutil.rmtree(trash)
                fsync_directory(trash.parent)
            purged = request.model_copy(update={"state": "purged"})
            self.repository.save_deletion_request(purged, connection=connection)
            entry = self.repository.get_model_entry(request.model_version, connection=connection)
            if entry is not None and entry.lifecycle_status is not LifecycleStatus.DELETED:
                self.repository.update_model_entry(
                    entry.model_version,
                    entry.revision,
                    {"lifecycle_status": LifecycleStatus.DELETED},
                    connection=connection,
                )
            self.repository.append_event(
                OperationEvent(
                    event_id=uuid4(),
                    operation_id=deletion_id,
                    operation="purge",
                    model_version=request.model_version,
                    phase="trash_purged",
                    result="succeeded",
                    occurred_at=datetime.now(UTC),
                ),
                connection=connection,
            )
        return self._deletion_result(purged, idempotent=False)

    @staticmethod
    def _deletion_result(request: DeletionRequest, *, idempotent: bool) -> dict[str, Any]:
        return {
            "status": "succeeded",
            "deletion_id": str(request.deletion_id),
            "model_version": request.model_version,
            "state": request.state,
            "trash_relpath": request.trash_relpath,
            "idempotent": idempotent,
        }
