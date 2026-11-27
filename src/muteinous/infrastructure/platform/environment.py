"""Shared identification of the host operating system."""

from __future__ import annotations

import sys
from enum import StrEnum
from typing import Final


class OperatingSystem(StrEnum):
    WINDOWS = "win32"
    LINUX = "linux"
    MACOS = "darwin"
    UNKNOWN = "unknown"


def _detect_os(platform: str) -> OperatingSystem:
    try:
        return OperatingSystem(platform)
    except ValueError:
        return OperatingSystem.UNKNOWN


CURRENT_OS: Final = _detect_os(sys.platform)
