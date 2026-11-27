"""GOG registry installation discovery."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import override

from .. import context
from . import _registry
from .base import InstallationProvider


def _windows_gog_records(
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
                                location = _registry._registry_text(state, game, "path")
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


class GOGProvider(InstallationProvider):
    """Discover GOG installations from read-only registry records."""

    def __init__(self, records: Iterable[tuple[object, object]] | None = None) -> None:
        self._records = records

    @override
    def discover(self, state: context.DiscoveryContext) -> None:
        records = (
            self._records if self._records is not None else _windows_gog_records(state)
        )
        for location, name in records:
            state.step()
            state.add(location, name, "gog")
