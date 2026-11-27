"""Steam library and manifest discovery."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import override

from muteinous.infrastructure.platform.environment import OperatingSystem

from .. import _registry, context
from ..models import Cancel
from .base import InstallationProvider

# Text KeyValues (Steam VDF/ACF), not a general Valve configuration interpreter.
_TOKEN = re.compile(r'\s+|//[^\r\n]*|"(?:\\.|[^"\\]++)*+"|[{}]|[^\s{}"]+')


def _tokens(text: str, cancelled: Cancel) -> Iterator[str]:
    position = 0
    while position < len(text):
        context._check(cancelled)
        match = _TOKEN.match(text, position)
        if match is None:
            raise ValueError("invalid KeyValues token")
        token = match.group()
        position = match.end()
        if not token.isspace() and not token.startswith("//"):
            yield token


def _string(token: str) -> str:
    if token in ("{", "}"):
        raise ValueError("expected KeyValues string")
    if token.startswith('"'):
        return re.sub(r'\\(["\\])', r"\1", token[1:-1])
    return token


def _keyvalues(text: str, cancelled: Cancel) -> dict[str, object]:
    tokens = iter(_tokens(text, cancelled))

    def parse(depth: int) -> dict[str, object]:
        if depth > 16:
            raise ValueError("KeyValues nesting limit")
        result: dict[str, object] = {}
        for key in tokens:
            if key == "}" and depth:
                return result
            key = _string(key).casefold()
            value = next(tokens, None)
            if value is None or key in result:
                raise ValueError("missing or ambiguous KeyValues value")
            result[key] = parse(depth + 1) if value == "{" else _string(value)
        if depth:
            raise ValueError("unclosed KeyValues object")
        return result

    return parse(0)


def _steam_library(state: context.DiscoveryContext, library: Path) -> None:
    directory = library / "steamapps"
    for path in state.files(directory):
        if not re.fullmatch(r"appmanifest_\d+\.acf", path.name, re.IGNORECASE):
            continue
        try:
            data = context._object(
                _keyvalues(state.read(path), state.cancelled)["appstate"]
            )
            folder = data.get("installdir")
            if not isinstance(folder, str) or not context._valid_component(folder):
                raise ValueError("invalid Steam installation folder")
            state.add(directory / "common" / folder, data.get("name"), "steam")
        except (OSError, ValueError, KeyError) as error:
            state.issue(path, str(error))


class SteamProvider(InstallationProvider):
    """Discover Steam installations using store-owned metadata sources."""

    def __init__(
        self, roots: Callable[[context.DiscoveryContext], Iterable[Path]] | None = None
    ) -> None:
        self._roots = roots

    @override
    def discover(self, state: context.DiscoveryContext) -> None:
        roots = self._roots
        if roots is None:
            if state.os != OperatingSystem.WINDOWS:
                state.issue("Steam", f"automatic discovery unavailable on {state.os}")
                return
            roots = self._windows_roots
        libraries: dict[str, Path] = {}
        seen_roots: set[str] = set()
        for root in roots(state):
            state.step()
            if not context._valid_path(root):
                state.issue("Steam root", "invalid library path")
                continue
            if str(root) in seen_roots:
                continue
            seen_roots.add(str(root))
            libraries[str(root)] = root
            manifest = root / "config" / "libraryfolders.vdf"
            try:
                try:
                    content = state.read(manifest)
                except FileNotFoundError:
                    manifest = root / "steamapps" / "libraryfolders.vdf"
                    content = state.read(manifest)
                values = context._object(
                    _keyvalues(content, state.cancelled)["libraryfolders"]
                )
                for key, value in values.items():
                    state.step()
                    if not key.isdecimal():
                        continue
                    location = value.get("path") if isinstance(value, dict) else value
                    if isinstance(location, str) and context._valid_path(
                        Path(location)
                    ):
                        library = Path(location)
                        libraries[str(library)] = library
                    else:
                        state.issue(manifest, "invalid Steam library path")
            except (OSError, ValueError, KeyError) as error:
                state.issue(manifest, str(error))
        for library in libraries.values():
            _steam_library(state, library)

    @staticmethod
    def _windows_roots(state: context.DiscoveryContext) -> Iterator[Path]:
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
