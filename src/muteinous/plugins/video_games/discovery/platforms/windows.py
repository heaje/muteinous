"""Windows launcher metadata sources and built-in provider composition."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from .. import context
from ..providers.base import InstallationProvider
from ..providers.epic import EpicProvider
from ..providers.gog import GOGProvider
from ..providers.steam import SteamProvider
from . import _registry


def _windows_steam_roots(state: context.DiscoveryContext) -> Iterator[Path]:
    import winreg

    for hive, value in (
        (winreg.HKEY_CURRENT_USER, "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, "InstallPath"),
    ):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            state.step()
            try:
                with winreg.OpenKey(
                    hive, r"Software\Valve\Steam", 0, winreg.KEY_READ | view
                ) as key:
                    location = _registry._registry_text(state, key, value)
                    if context._valid_path(Path(location)):
                        yield Path(location)
                    else:
                        state.issue("Steam registry", "invalid Steam root")
            except FileNotFoundError:
                pass
            except (OSError, ValueError) as error:
                state.issue("Steam registry", str(error))
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        if program_files := os.environ.get(variable):
            path = Path(program_files) / "Steam"
            if context._valid_path(path) and path.is_dir():
                yield path


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


def windows_providers(
    state: context.DiscoveryContext,
) -> tuple[InstallationProvider, ...]:
    program_data = os.environ.get("ProgramData")
    epic = (
        Path(program_data) / "Epic/EpicGamesLauncher/Data/Manifests"
        if program_data
        else None
    )
    if epic is None or not context._valid_path(epic):
        state.issue("Epic", "missing or invalid ProgramData location")
        epic = None
    return (
        SteamProvider(_windows_steam_roots),
        EpicProvider(epic),
        GOGProvider(_windows_gog_records),
    )
