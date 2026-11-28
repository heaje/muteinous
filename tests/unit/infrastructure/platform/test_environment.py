"""Host operating-system identification contract."""

import sys

import pytest

from muteinous.infrastructure.platform.environment import (
    CURRENT_OS,
    OperatingSystem,
    _detect_os,
)


@pytest.mark.portable
@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("win32", OperatingSystem.WINDOWS),
        ("linux", OperatingSystem.LINUX),
        ("darwin", OperatingSystem.MACOS),
        ("unsupported", OperatingSystem.UNKNOWN),
    ],
)
def test_platform_mapping(platform: str, expected: OperatingSystem) -> None:
    assert _detect_os(platform) is expected


@pytest.mark.portable
def test_current_os_matches_host() -> None:
    assert CURRENT_OS.value == sys.platform
