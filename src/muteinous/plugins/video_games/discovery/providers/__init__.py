"""Explicit built-in launcher discovery registration."""

from .base import InstallationProvider
from .epic import EpicProvider
from .gog import GOGProvider
from .steam import SteamProvider


def built_in_providers() -> tuple[InstallationProvider, ...]:
    return SteamProvider(), EpicProvider(), GOGProvider()
