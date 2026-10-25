"""Validated atomic commit point for the model served by inference."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from house_price.registry.atomic import atomic_write_json, safe_relative_path


class ChampionPointer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0.0"] = "1.0.0"
    model_version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    manifest_path: str
    manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def manifest_matches_model(self) -> "ChampionPointer":
        if self.manifest_path != f"models/{self.model_version}/manifest.json":
            raise ValueError("unsafe pointer manifest path does not match model identity")
        return self


def read_pointer(root: Path) -> ChampionPointer | None:
    path = root / "current.json"
    if not path.is_file():
        return None
    pointer = ChampionPointer.model_validate_json(path.read_text(encoding="utf-8"))
    safe_relative_path(root, pointer.manifest_path)
    return pointer


def write_pointer(path: Path, pointer: ChampionPointer) -> None:
    atomic_write_json(path, pointer.model_dump(mode="json"))


def pointer_json(pointer: ChampionPointer) -> str:
    return json.dumps(pointer.model_dump(mode="json"), sort_keys=True)
