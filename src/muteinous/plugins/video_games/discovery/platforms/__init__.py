"""Select implemented platform metadata sources without guessing locations."""

from __future__ import annotations

import sys

from ..context import DiscoveryContext
from ..providers.base import InstallationProvider


def current_providers(
    state: DiscoveryContext,
) -> tuple[InstallationProvider, ...] | None:
    if sys.platform == "win32":
        from .windows import windows_providers

        return windows_providers(state)
    return None
