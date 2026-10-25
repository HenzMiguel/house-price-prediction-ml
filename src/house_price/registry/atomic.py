"""Crash-safe and path-safe filesystem primitives for the model registry."""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative_path(root: Path, relative: str | Path) -> Path:
    raw = PurePosixPath(str(relative))
    if raw.is_absolute() or not raw.parts or ".." in raw.parts or "." in raw.parts:
        raise ValueError(f"unsafe relative path: {relative}")
    root = root.resolve()
    candidate = root.joinpath(*raw.parts)
    current = root
    for part in raw.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"symlink is not allowed in registry path: {relative}")
    try:
        candidate.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ValueError(f"unsafe relative path: {relative}") from exc
    return candidate


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    atomic_write_bytes(path, (json.dumps(value, sort_keys=True) + "\n").encode())


def move_immutable(source: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"immutable destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.stat().st_dev != destination.parent.stat().st_dev:
        raise OSError("source and destination must be on the same filesystem")
    os.replace(source, destination)
    fsync_directory(destination.parent)


def move_to_trash(source: Path, trash: Path) -> None:
    trash.parent.mkdir(parents=True, exist_ok=True)
    move_immutable(source, trash)
