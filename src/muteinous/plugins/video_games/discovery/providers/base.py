"""The internal contract for built-in launcher discovery."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..context import DiscoveryContext


class InstallationProvider(ABC):
    """Find candidates using the shared context, without reading game content."""

    @abstractmethod
    def discover(self, state: DiscoveryContext) -> None:
        """Report candidates and issues into the caller-owned context."""
