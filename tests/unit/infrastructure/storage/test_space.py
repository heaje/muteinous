"""Storage unit tests for the corresponding infrastructure module."""

from __future__ import annotations

import errno
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

from muteinous.infrastructure.storage._filesystem import InsufficientSpace, StorageError
from muteinous.infrastructure.storage.space import (
    SpaceAssessment,
    SpaceRequirement,
    preflight,
    translate_write_error,
)

pytestmark = pytest.mark.portable


@pytest.mark.parametrize(
    ("minimum", "estimate"),
    [
        (-1, None),
        (True, None),
        (1.5, None),
        (5, 4),
        (1, True),
        (1, 1.5),
    ],
)
def test_space_requirement_rejects_invalid_bounds(
    tmp_path: Path, minimum: int, estimate: int | None
) -> None:
    with pytest.raises(ValueError, match="Invalid space requirement"):
        SpaceRequirement(tmp_path, minimum, estimate)


def test_space_requirement_is_frozen(tmp_path: Path) -> None:
    requirement = SpaceRequirement(tmp_path, 1, 2)
    with pytest.raises(FrozenInstanceError):
        setattr(requirement, "minimum", 0)


def test_space_assessment_is_frozen(tmp_path: Path) -> None:
    assessment = SpaceAssessment(tmp_path, 10, 1, 2)
    with pytest.raises(FrozenInstanceError):
        setattr(assessment, "available", 0)


def test_preflight_rejects_parent_components_before_normalizing(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "staging").mkdir(parents=True)
    traversing_directory = root / "staging" / ".." / "staging"
    with pytest.raises(StorageError, match="parent|traversal"):
        preflight([SpaceRequirement(traversing_directory, 0)], root=root)


@pytest.mark.parametrize(
    ("available", "minimum", "estimate", "shortage", "uncertain"),
    [
        (10, 10, 10, False, False),
        (9, 10, None, True, None),
        (10, 1, 10, False, False),
        (10, 1, 11, False, True),
    ],
)
def test_preflight_exact_space_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    available: int,
    minimum: int,
    estimate: int | None,
    shortage: bool,
    uncertain: bool | None,
) -> None:
    monkeypatch.setattr(
        "muteinous.infrastructure.storage.space.shutil.disk_usage",
        lambda path: SimpleNamespace(free=available),
    )
    requirement = SpaceRequirement(tmp_path, minimum, estimate)
    if shortage:
        with pytest.raises(InsufficientSpace):
            preflight([requirement])
        return

    (assessment,) = preflight([requirement])
    assert assessment.available == available
    assert assessment.minimum == minimum
    assert assessment.uncertain is uncertain


def test_preflight_uses_lowest_free_space_report_on_same_device(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    free = {first: 20, second: 8}

    monkeypatch.setattr(
        "muteinous.infrastructure.storage.space.checked_directory",
        lambda path, *, root=None: SimpleNamespace(st_dev=7),
    )
    monkeypatch.setattr(
        "muteinous.infrastructure.storage.space.shutil.disk_usage",
        lambda path: SimpleNamespace(free=free[path]),
    )
    (assessment,) = preflight(
        [
            SpaceRequirement(first, 2, 3),
            SpaceRequirement(second, 3, 4),
        ]
    )
    assert assessment.available == 8
    assert assessment.minimum == 5
    assert assessment.estimate == 7


def test_preflight_groups_and_checks_each_device_independently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "device-one-a"
    second = tmp_path / "device-one-b"
    third = tmp_path / "device-two"
    first.mkdir()
    second.mkdir()
    third.mkdir()
    devices = {first: 11, second: 11, third: 22}
    free = {first: 8, second: 12, third: 7}

    def checked_device(path: Path, *, root: Path | None = None) -> SimpleNamespace:
        return SimpleNamespace(st_dev=devices[path])

    monkeypatch.setattr(
        "muteinous.infrastructure.storage.space.checked_directory", checked_device
    )
    monkeypatch.setattr(
        "muteinous.infrastructure.storage.space.shutil.disk_usage",
        lambda path: SimpleNamespace(free=free[path]),
    )
    assessments = preflight(
        [
            SpaceRequirement(first, 2, 3),
            SpaceRequirement(second, 3, 4),
            SpaceRequirement(third, 6, 7),
        ]
    )
    assert [
        (
            assessment.directory,
            assessment.available,
            assessment.minimum,
            assessment.estimate,
        )
        for assessment in assessments
    ] == [(first, 8, 5, 7), (third, 7, 6, 7)]


@pytest.mark.portable
@pytest.mark.parametrize(
    ("estimates", "available", "expected", "uncertain"),
    [
        ((4, 7), 10, 11, True),
        ((4, 5), 10, 9, False),
    ],
)
def test_preflight_sums_finite_estimates_and_reports_uncertainty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    estimates: tuple[int, int],
    available: int,
    expected: int,
    uncertain: bool,
) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    monkeypatch.setattr(
        "muteinous.infrastructure.storage.space.shutil.disk_usage",
        lambda path: SimpleNamespace(free=available),
    )
    (assessment,) = preflight(
        [
            SpaceRequirement(tmp_path, 1, estimates[0]),
            SpaceRequirement(staging, 1, estimates[1]),
        ]
    )
    assert assessment.estimate == expected
    assert assessment.uncertain is uncertain


@pytest.mark.portable
@pytest.mark.parametrize("winerror", [39, 112, 1295])
def test_windows_disk_full_errors_are_classified_as_insufficient_space(
    winerror: int,
) -> None:
    error = OSError(errno.EINVAL, "Windows disk capacity error")
    setattr(error, "winerror", winerror)
    with pytest.raises(InsufficientSpace) as exc:
        translate_write_error(error)
    assert exc.value.__cause__ is error


@pytest.mark.portable
def test_edquot_is_classified_as_insufficient_space_when_available() -> None:
    quota_errno = getattr(errno, "EDQUOT", None)
    if quota_errno is not None:
        with pytest.raises(InsufficientSpace):
            translate_write_error(OSError(quota_errno, "disk quota exceeded"))
