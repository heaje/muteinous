"""GOG installation discovery from supplied metadata records."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import override

from .. import context
from .base import InstallationProvider


class GOGProvider(InstallationProvider):
    """Discover GOG installations from supplied read-only metadata records."""

    def __init__(
        self,
        records: Callable[[context.DiscoveryContext], Iterable[tuple[object, object]]],
    ) -> None:
        self._records = records

    @override
    def discover(self, state: context.DiscoveryContext) -> None:
        for location, name in self._records(state):
            state.step()
            state.add(location, name, "gog")
