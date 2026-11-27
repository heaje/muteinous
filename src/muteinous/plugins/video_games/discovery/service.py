"""Coordinate built-in discovery and manual folder intake."""

from __future__ import annotations

import sys
from collections.abc import Iterable
from pathlib import Path

from . import context
from .models import Cancel, DiscoveryResult
from .providers.base import InstallationProvider
from .providers.epic import EpicProvider
from .providers.gog import GOGProvider
from .providers.steam import SteamProvider


def _discover(
    state: context.DiscoveryContext,
    providers: Iterable[InstallationProvider],
) -> DiscoveryResult:
    try:
        for provider in providers:
            context._check(state.cancelled)
            provider.discover(state)
    except context._LimitReached:
        state.truncated = True
        state.issue("discovery", "metadata or entry budget exhausted")
    context._check(state.cancelled)
    return DiscoveryResult(
        tuple(state.candidates), tuple(state.issues), state.truncated
    )


def discover_windows(*, cancelled: Cancel = context._never_cancel) -> DiscoveryResult:
    """Discover local Windows launcher candidates; no game content is scanned."""
    state = context.DiscoveryContext(cancelled)
    context._check(cancelled)
    if sys.platform != "win32":
        return DiscoveryResult((), ("Windows launcher discovery unavailable",), False)
    providers = (SteamProvider(), EpicProvider.from_windows(state), GOGProvider())
    return _discover(state, providers)


def select_folder(
    path: Path, *, cancelled: Cancel = context._never_cancel
) -> DiscoveryResult:
    """Manual folder intake remains available without any launcher."""
    state = context.DiscoveryContext(cancelled)
    state.add(path, path.name, "manual")
    context._check(cancelled)
    return DiscoveryResult(tuple(state.candidates), tuple(state.issues), False)
