"""Small controlled-root filesystem and canonical metadata helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any


class StorageError(RuntimeError):
    """Storage cannot establish the required safety or validity evidence."""


class InsufficientSpace(StorageError):
    """A known storage requirement cannot be satisfied."""


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def read_json(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict) or canonical_json(value) != raw:
            raise ValueError("not a canonical JSON object")
    except (ValueError, TypeError, RecursionError) as exc:
        raise StorageError("Invalid canonical JSON metadata") from exc
    return value


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def is_digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def is_token(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value) is not None


def safe_name(name: str) -> None:
    # Preserve exact names; refuse nonportable or ambiguous components.
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved.update(f"{prefix}{n}" for prefix in ("COM", "LPT") for n in "123456789¹²³")
    if (
        not name
        or name in {".", ".."}
        or name[-1] in " ."
        or any(c in '<>:"/\\|?*' or ord(c) < 32 for c in name)
        or name.split(".", 1)[0].upper() in reserved
    ):
        raise StorageError(f"Unsafe path component: {name!r}")
    try:
        name.encode("utf-8")
    except UnicodeError as exc:
        raise StorageError("Path is not valid UTF-8") from exc


def checked_stat(path: Path, *, directory: bool) -> os.stat_result:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or (
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    ):
        raise StorageError(f"Unsafe link or reparse point: {path}")
    if directory:
        valid = stat.S_ISDIR(info.st_mode)
    else:
        valid = stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    if not valid:
        raise StorageError(f"Unexpected filesystem entry: {path}")
    return info


def _reject_parent_components(path: Path) -> None:
    if ".." in path.parts:
        raise StorageError(f"Parent traversal is not allowed: {path}")


def checked_directory(path: Path, *, root: Path | None = None) -> os.stat_result:
    """Check a directory and its controlled-root path without following links.

    When ``root`` is supplied, ancestors above that caller-established boundary
    are intentionally outside this component's control and are not inspected.
    """
    _reject_parent_components(path)
    if root is not None:
        _reject_parent_components(root)
    path = path.absolute()
    if root is None:
        components = [*reversed(path.parents), path]
    else:
        root = root.absolute()
        try:
            relative = path.relative_to(root)
        except ValueError as exc:
            raise StorageError(f"Directory is outside controlled root: {path}") from exc
        components = [root]
        for part in relative.parts:
            components.append(components[-1] / part)
    for component in components:
        info = checked_stat(component, directory=True)
    return info


def read_regular(path: Path, *, root: Path | None = None) -> bytes:
    checked_directory(path.parent, root=root)
    checked_stat(path, directory=False)
    return path.read_bytes()


def walk_files(
    root: Path,
    *,
    allow_empty: bool = False,
    controlled_root: Path | None = None,
) -> list[Path]:
    device = checked_directory(root, root=controlled_root).st_dev
    files: list[Path] = []

    def visit(directory: Path) -> None:
        if checked_stat(directory, directory=True).st_dev != device:
            raise StorageError(f"Unexpected filesystem boundary: {directory}")
        entries = sorted(directory.iterdir())
        if not entries and not allow_empty:
            raise StorageError(f"Unexpected empty directory: {directory}")
        names: set[str] = set()
        for path in entries:
            safe_name(path.name)
            folded = path.name.casefold()
            if folded in names:
                raise StorageError(f"Ambiguous path: {path}")
            names.add(folded)
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                visit(path)
            else:
                if checked_stat(path, directory=False).st_dev != device:
                    raise StorageError(f"Unexpected filesystem boundary: {path}")
                files.append(path)

    visit(root)
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def file_record(root: Path, path: Path) -> dict[str, object]:
    before = checked_stat(path, directory=False)
    hasher = hashlib.sha256()
    length = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            hasher.update(block)
            length += len(block)
    after = checked_stat(path, directory=False)
    if (
        length != before.st_size
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ctime_ns != after.st_ctime_ns
        or before.st_ino != after.st_ino
        or before.st_dev != after.st_dev
    ):
        raise StorageError(f"File changed during validation: {path}")
    return {
        "path": path.relative_to(root).as_posix(),
        "length": length,
        "sha256": hasher.hexdigest(),
    }
