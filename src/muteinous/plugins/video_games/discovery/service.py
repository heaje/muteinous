"""Coordinate built-in discovery and manual folder intake."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from muteinous.infrastructure.platform.environment import CURRENT_OS, OperatingSystem

from . import context, providers
from .models import Cancel, DiscoveryResult
from .providers.base import InstallationProvider


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


def discover_installations(
    *, cancelled: Cancel = context._never_cancel
) -> DiscoveryResult:
    """Discover candidates using supported sources for the current platform."""
    state = context.DiscoveryContext(cancelled, os=CURRENT_OS)
    context._check(cancelled)
    return _discover(state, providers.built_in_providers())


def discover_windows(*, cancelled: Cancel = context._never_cancel) -> DiscoveryResult:
    """Compatibility entry point restricted to Windows launcher discovery."""
    if CURRENT_OS != OperatingSystem.WINDOWS:
        context._check(cancelled)
        return DiscoveryResult((), ("Windows launcher discovery unavailable",), False)
    return discover_installations(cancelled=cancelled)


def select_folder(
    path: Path, *, cancelled: Cancel = context._never_cancel
) -> DiscoveryResult:
    """Manual folder intake remains available without any launcher."""
    state = context.DiscoveryContext(cancelled)
    state.add(path, path.name, "manual")
    context._check(cancelled)
    return DiscoveryResult(tuple(state.candidates), tuple(state.issues), False)
