"""GOG installation discovery from supplied metadata records."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import override

from muteinous.infrastructure.platform.environment import OperatingSystem

from .. import _registry, context
from .base import InstallationProvider


class GOGProvider(InstallationProvider):
    """Discover GOG installations from supplied read-only metadata records."""

    def __init__(
        self,
        records: Callable[[context.DiscoveryContext], Iterable[tuple[object, object]]]
        | None = None,
    ) -> None:
        self._records = records

    @override
    def discover(self, state: context.DiscoveryContext) -> None:
        records = self._records
        if records is None:
            if state.os != OperatingSystem.WINDOWS:
                state.issue("GOG", f"automatic discovery unavailable on {state.os}")
                return
            records = self._windows_records
        for location, name in records(state):
            state.step()
            state.add(location, name, "gog")

    @staticmethod
    def _windows_records(
        state: context.DiscoveryContext,
    ) -> Iterator[tuple[object, object]]:
        import winreg

        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
                state.step()
                try:
                    with winreg.OpenKey(
                        hive, r"Software\GOG.com\Games", 0, winreg.KEY_READ | view
                    ) as games:
                        count, _, _ = winreg.QueryInfoKey(games)
                        for index in range(count):
                            state.step()
                            try:
                                identifier = winreg.EnumKey(games, index)
                                with winreg.OpenKey(
                                    games, identifier, 0, winreg.KEY_READ | view
                                ) as game:
                                    location = _registry._registry_text(
                                        state, game, "path"
                                    )
                                    name: str | None
                                    try:
                                        name = _registry._registry_text(
                                            state, game, "gameName"
                                        )
                                    except FileNotFoundError:
                                        name = None
                                    except (OSError, ValueError) as error:
                                        state.issue("GOG registry name", str(error))
                                        name = None
                                    yield location, name
                            except (OSError, ValueError) as error:
                                state.issue("GOG registry record", str(error))
                except FileNotFoundError:
                    pass
                except OSError as error:
                    state.issue("GOG registry", str(error))
