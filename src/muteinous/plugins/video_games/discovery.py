"""Read-only launcher candidates and provisional, bounded installation probes."""

from __future__ import annotations

import json
import ntpath
import os
import re
import stat
import sys
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, SupportsInt

Source = Literal["steam", "epic", "gog", "manual"]
Availability = Literal["available", "missing", "inaccessible"]
Cancel = Callable[[], bool]

_MAX_ENTRIES = 4096
_MAX_METADATA = 1024 * 1024
_MAX_TOTAL_METADATA = 16 * _MAX_METADATA
_MAX_REGISTRY_VALUE = 64 * 1024
_MAX_PROBE_ENTRIES = 128
_MAX_PROBE_DEPTH = 2


class DiscoveryCancelled(Exception):
    """The caller cancelled; no partial result should be published."""


class _LimitReached(Exception):
    pass


def _never_cancel() -> bool:
    return False


def _check(cancelled: Cancel) -> None:
    if cancelled():
        raise DiscoveryCancelled


@dataclass(frozen=True)
class Candidate:
    path: Path
    name: str
    sources: tuple[Source, ...]
    availability: Availability


@dataclass(frozen=True)
class DiscoveryResult:
    candidates: tuple[Candidate, ...]
    issues: tuple[str, ...]
    truncated: bool


@dataclass(frozen=True)
class ProbeResult:
    # A signature is evidence for further investigation, not a supported reader.
    ast_signature: bool
    entries_examined: int
    issues: tuple[str, ...]
    truncated: bool


@dataclass
class _Discovery:
    cancelled: Cancel
    candidates: list[Candidate] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    identities: dict[str, int] = field(default_factory=dict)
    entries: int = 0
    bytes_read: int = 0
    truncated: bool = False

    def step(self) -> None:
        _check(self.cancelled)
        if self.entries >= _MAX_ENTRIES:
            raise _LimitReached
        self.entries += 1

    def issue(self, location: object, detail: str) -> None:
        self.issues.append(f"{location}: {detail}")

    def add(self, location: object, name: object, source: Source) -> None:
        _check(self.cancelled)
        if not isinstance(location, (str, Path)) or not str(location).strip():
            self.issue(source, "missing or invalid installation path")
            return
        path = Path(location)
        if not _valid_path(path):
            self.issue(source, "invalid installation path")
            return
        label = path.name
        if isinstance(name, str) and name.strip():
            if _valid_text(name):
                label = name
            else:
                self.issue(source, "invalid installation display name")
        candidate, identity = _candidate(path, label, source)
        if identity is not None and identity in self.identities:
            index = self.identities[identity]
            previous = self.candidates[index]
            if source not in previous.sources:
                self.candidates[index] = replace(
                    previous, sources=(*previous.sources, source)
                )
        else:
            if identity is not None:
                self.identities[identity] = len(self.candidates)
            self.candidates.append(candidate)

    def read(self, path: Path) -> str:
        _check(self.cancelled)
        remaining = _MAX_TOTAL_METADATA - self.bytes_read
        if remaining <= 0:
            raise _LimitReached
        limit = min(remaining, _MAX_METADATA)
        info = path.lstat()
        if not _ordinary(info) or not stat.S_ISREG(info.st_mode):
            raise ValueError("metadata is not an ordinary file")
        if info.st_size > limit:
            self.truncated = True
            raise ValueError("metadata exceeds read limit")
        with path.open("rb", buffering=0) as stream:
            raw = stream.read(limit + 1)
        self.bytes_read += len(raw)
        _check(self.cancelled)
        if len(raw) > limit:
            self.truncated = True
            raise ValueError("metadata exceeds read limit")
        return raw.decode("utf-8-sig")

    def files(self, directory: Path) -> Iterator[Path]:
        _check(self.cancelled)
        try:
            info = directory.lstat()
            if not _ordinary(info) or not stat.S_ISDIR(info.st_mode):
                raise ValueError("metadata directory is not an ordinary directory")
            with os.scandir(directory) as entries:
                for entry in entries:
                    self.step()
                    yield Path(entry.path)
        except (OSError, ValueError) as error:
            self.issue(directory, str(error))


def _ordinary(info: os.stat_result) -> bool:
    # Do not follow symlinks or Windows junctions/reparse points during probes.
    return not (
        stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
    )


def _valid_text(value: str) -> bool:
    return "\x00" not in value and not any(
        0xD800 <= ord(char) <= 0xDFFF for char in value
    )


def _valid_path(path: Path) -> bool:
    if not path.is_absolute() or ".." in path.parts or not _valid_text(str(path)):
        return False
    if os.name == "nt":
        if path.anchor.startswith(("\\\\?\\", "\\\\.\\")):
            return False
        if any(ntpath.isreserved(part) for part in path.parts[1:]):
            return False
    return True


def _candidate(path: Path, name: str, source: Source) -> tuple[Candidate, str | None]:
    try:
        identity = path.resolve(strict=True)
        if not stat.S_ISDIR(identity.stat().st_mode):
            return Candidate(path, name, (source,), "missing"), None
    except FileNotFoundError, NotADirectoryError:
        return Candidate(path, name, (source,), "missing"), None
    except OSError, RuntimeError, ValueError:
        return Candidate(path, name, (source,), "inaccessible"), None
    return Candidate(path, name, (source,), "available"), str(identity)


# Text KeyValues (Steam VDF/ACF), not a general Valve configuration interpreter.
_TOKEN = re.compile(r'\s+|//[^\r\n]*|"(?:\\.|[^"\\]++)*+"|[{}]|[^\s{}"]+')


def _tokens(text: str, cancelled: Cancel) -> Iterator[str]:
    position = 0
    while position < len(text):
        _check(cancelled)
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


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("expected metadata object")
    return value


def _steam_library(state: _Discovery, library: Path) -> None:
    directory = library / "steamapps"
    for path in state.files(directory):
        if not re.fullmatch(r"appmanifest_\d+\.acf", path.name, re.IGNORECASE):
            continue
        try:
            data = _object(_keyvalues(state.read(path), state.cancelled)["appstate"])
            folder = data.get("installdir")
            if (
                not isinstance(folder, str)
                or not folder.strip()
                or folder in (".", "..")
                or any(char in folder for char in "/\\:\x00")
                or ntpath.isreserved(folder)
            ):
                raise ValueError("invalid Steam installation folder")
            state.add(directory / "common" / folder, data.get("name"), "steam")
        except (OSError, ValueError, KeyError) as error:
            state.issue(path, str(error))


def _steam(state: _Discovery, roots: Iterable[Path]) -> None:
    libraries: dict[str, Path] = {}
    seen_roots: set[str] = set()
    for root in roots:
        state.step()
        if not _valid_path(root):
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
            values = _object(_keyvalues(content, state.cancelled)["libraryfolders"])
            for key, value in values.items():
                state.step()
                if not key.isdecimal():
                    continue
                location = value.get("path") if isinstance(value, dict) else value
                if isinstance(location, str) and _valid_path(Path(location)):
                    library = Path(location)
                    libraries[str(library)] = library
                else:
                    state.issue(manifest, "invalid Steam library path")
        except (OSError, ValueError, KeyError) as error:
            state.issue(manifest, str(error))
    for library in libraries.values():
        _steam_library(state, library)


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("ambiguous JSON metadata key")
        result[key] = value
    return result


def _epic(state: _Discovery, directory: Path) -> None:
    for path in state.files(directory):
        if path.suffix.lower() != ".item":
            continue
        try:
            data = _object(json.loads(state.read(path), object_pairs_hook=_json_object))
            if data.get("bIsIncompleteInstall") is True:
                state.issue(path, "launcher reports incomplete installation")
            state.add(data.get("InstallLocation"), data.get("DisplayName"), "epic")
        except (OSError, ValueError, RecursionError) as error:
            state.issue(path, str(error))


def _gog(state: _Discovery, records: Iterable[tuple[object, object]]) -> None:
    for location, name in records:
        state.step()
        state.add(location, name, "gog")


def _registry_text(state: _Discovery, key: SupportsInt, name: str) -> str:
    """Read a single REG_SZ with a fixed buffer, never an unbounded value query."""
    import ctypes
    import winreg
    from ctypes import wintypes

    _check(state.cancelled)
    remaining = _MAX_TOTAL_METADATA - state.bytes_read
    if remaining <= 0:
        raise _LimitReached
    limit = min(remaining, _MAX_REGISTRY_VALUE)
    buffer = ctypes.create_string_buffer(limit)
    size = wintypes.DWORD(limit)
    kind = wintypes.DWORD()
    query = ctypes.WinDLL("advapi32.dll").RegQueryValueExW
    query.argtypes = [
        wintypes.HKEY,
        wintypes.LPCWSTR,
        wintypes.LPDWORD,
        wintypes.LPDWORD,
        wintypes.LPVOID,
        wintypes.LPDWORD,
    ]
    query.restype = wintypes.LONG
    status: int = query(
        wintypes.HKEY(int(key)),
        name,
        None,
        ctypes.byref(kind),
        buffer,
        ctypes.byref(size),
    )
    _check(state.cancelled)
    if status == 234:  # ERROR_MORE_DATA; do not allocate a larger buffer.
        state.truncated = True
        raise ValueError("registry metadata exceeds read limit")
    if status == 2:  # ERROR_FILE_NOT_FOUND
        raise FileNotFoundError(name)
    if status:
        raise ctypes.WinError(status)
    state.bytes_read += size.value
    if kind.value != winreg.REG_SZ:
        raise ValueError("unsupported registry metadata type")
    value = buffer.raw[: size.value].decode("utf-16-le").removesuffix("\x00")
    if not _valid_text(value):
        raise ValueError("invalid registry metadata string")
    return value


def _windows_steam_roots(state: _Discovery) -> Iterator[Path]:
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
                    location = _registry_text(state, key, value)
                    if _valid_path(Path(location)):
                        yield Path(location)
                    else:
                        state.issue("Steam registry", "invalid Steam root")
            except FileNotFoundError:
                pass
            except (OSError, ValueError) as error:
                state.issue("Steam registry", str(error))
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        if location := os.environ.get(variable):
            path = Path(location) / "Steam"
            if _valid_path(path) and path.is_dir():
                yield path


def _windows_gog_records(state: _Discovery) -> Iterator[tuple[object, object]]:
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
                                location = _registry_text(state, game, "path")
                                name: str | None
                                try:
                                    name = _registry_text(state, game, "gameName")
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


def _discover(
    state: _Discovery,
    steam_roots: Iterable[Path],
    epic_directory: Path | None,
    gog_records: Iterable[tuple[object, object]],
) -> DiscoveryResult:
    try:
        _steam(state, steam_roots)
        if epic_directory is not None:
            _epic(state, epic_directory)
        _gog(state, gog_records)
    except _LimitReached:
        state.truncated = True
        state.issue("discovery", "metadata or entry budget exhausted")
    _check(state.cancelled)
    return DiscoveryResult(
        tuple(state.candidates), tuple(state.issues), state.truncated
    )


def discover_windows(*, cancelled: Cancel = _never_cancel) -> DiscoveryResult:
    """Discover local Windows launcher candidates; no game content is scanned."""
    state = _Discovery(cancelled)
    _check(cancelled)
    if sys.platform != "win32":
        return DiscoveryResult((), ("Windows launcher discovery unavailable",), False)
    program_data = os.environ.get("ProgramData")
    epic = (
        Path(program_data) / "Epic/EpicGamesLauncher/Data/Manifests"
        if program_data
        else None
    )
    if epic is None or not _valid_path(epic):
        state.issue("Epic", "missing or invalid ProgramData location")
        epic = None
    return _discover(
        state, _windows_steam_roots(state), epic, _windows_gog_records(state)
    )


def select_folder(path: Path, *, cancelled: Cancel = _never_cancel) -> DiscoveryResult:
    """Manual folder intake remains available without any launcher."""
    state = _Discovery(cancelled)
    state.add(path, path.name, "manual")
    _check(cancelled)
    return DiscoveryResult(tuple(state.candidates), tuple(state.issues), False)


def probe_installation(
    candidate: Candidate, *, cancelled: Cancel = _never_cancel
) -> ProbeResult:
    """Inspect a shallow bounded sample of ordinary files, never decode or hash."""
    _check(cancelled)
    if candidate.availability != "available":
        return ProbeResult(False, 0, ("installation unavailable",), True)
    issues: list[str] = []
    found = False
    examined = 0
    truncated = False
    pending: deque[tuple[Path, int]] = deque([(candidate.path, 0)])
    while pending and examined < _MAX_PROBE_ENTRIES:
        directory, depth = pending.popleft()
        _check(cancelled)
        try:
            info = directory.lstat()
            if not _ordinary(info) or not stat.S_ISDIR(info.st_mode):
                truncated = True
                issues.append(f"{directory}: not an ordinary directory")
                continue
            with os.scandir(directory) as entries:
                for entry in entries:
                    _check(cancelled)
                    if examined >= _MAX_PROBE_ENTRIES:
                        truncated = True
                        break
                    examined += 1
                    try:
                        path = Path(entry.path)
                        info = path.lstat()
                        if not _ordinary(info):
                            truncated = True
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            if depth < _MAX_PROBE_DEPTH:
                                pending.append((path, depth + 1))
                            else:
                                truncated = True
                        elif stat.S_ISREG(info.st_mode):
                            with path.open("rb", buffering=0) as stream:
                                found |= stream.read(4) == b"STRM"
                        else:
                            truncated = True
                    except OSError as error:
                        truncated = True
                        issues.append(f"{entry.path}: {error}")
        except OSError as error:
            truncated = True
            issues.append(f"{directory}: {error}")
    _check(cancelled)
    return ProbeResult(found, examined, tuple(issues), truncated or bool(pending))
