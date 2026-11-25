"""Advisory, bounded free-space checks without cache eviction."""

from __future__ import annotations

import errno
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Never

from ._filesystem import (
    InsufficientSpace,
    StorageError,
    _reject_parent_components,
    checked_directory,
)


@dataclass(frozen=True)
class SpaceRequirement:
    """Additional bytes needed on an existing relevant filesystem.

    A missing estimate means the upper requirement is uncertain; minimum is
    always the known required lower bound.
    """

    directory: Path
    minimum: int
    estimate: int | None = None

    def __post_init__(self) -> None:
        if (
            type(self.minimum) is not int
            or self.minimum < 0
            or (
                self.estimate is not None
                and (type(self.estimate) is not int or self.estimate < self.minimum)
            )
        ):
            raise ValueError("Invalid space requirement")


@dataclass(frozen=True)
class SpaceAssessment:
    directory: Path
    available: int
    minimum: int
    estimate: int | None

    @property
    def uncertain(self) -> bool:
        return self.estimate is None or self.estimate > self.available


def preflight(
    requirements: Iterable[SpaceRequirement], *, root: Path | None = None
) -> tuple[SpaceAssessment, ...]:
    """Aggregate simultaneous requirements by filesystem; never reserve bytes."""
    grouped: dict[int, list[SpaceRequirement]] = {}
    for requirement in requirements:
        _reject_parent_components(requirement.directory)
        if root is not None:
            _reject_parent_components(root)
        directory = requirement.directory.absolute()
        if root is None:
            boundary = directory
        else:
            controlled_root = root.absolute()
            try:
                directory.relative_to(controlled_root)
            except ValueError:
                # Additional caller-supplied requirements may be on another
                # filesystem; their requested directory is their boundary.
                boundary = directory
            else:
                boundary = controlled_root
        device = checked_directory(directory, root=boundary).st_dev
        grouped.setdefault(device, []).append(requirement)
    assessments = []
    for group in grouped.values():
        directory = group[0].directory
        minimum = sum(item.minimum for item in group)
        estimates = [item.estimate for item in group]
        estimate = (
            None if None in estimates else sum(e for e in estimates if e is not None)
        )
        # Use the lowest reported free capacity if different directories have quotas.
        try:
            available = min(shutil.disk_usage(item.directory).free for item in group)
        except OSError as exc:
            raise StorageError(
                f"Cannot establish available space at {directory}"
            ) from exc
        if available < minimum:
            raise InsufficientSpace(
                f"Insufficient space at {directory}: {available} available, "
                f"{minimum} required"
            )
        assessments.append(SpaceAssessment(directory, available, minimum, estimate))
    return tuple(assessments)


def translate_write_error(exc: OSError) -> Never:
    """Preserve ordinary I/O errors; classify actual insufficient-space failures."""
    if exc.errno in {errno.ENOSPC, getattr(errno, "EDQUOT", -1)} or getattr(
        exc, "winerror", None
    ) in {39, 112, 1295}:
        raise InsufficientSpace(
            "Storage ran out of space; affected work stopped"
        ) from exc
    raise exc
