"""Synthetic launcher metadata and bounded read-only probing contracts."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest

from muteinous.infrastructure.platform.environment import OperatingSystem
from muteinous.plugins.video_games import discovery
from muteinous.plugins.video_games.discovery import (
    _registry,
    context,
    probe,
    providers,
    service,
)
from muteinous.plugins.video_games.discovery.providers.base import InstallationProvider
from muteinous.plugins.video_games.discovery.providers.epic import EpicProvider
from muteinous.plugins.video_games.discovery.providers.gog import GOGProvider
from muteinous.plugins.video_games.discovery.providers.steam import SteamProvider


def _vdf_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace('"', '\\"')


def _steam_manifest(library: Path, folder: str, app: int = 1) -> Path:
    steamapps = library / "steamapps"
    steamapps.mkdir(parents=True, exist_ok=True)
    manifest = steamapps / f"appmanifest_{app}.acf"
    manifest.write_text(
        f'"AppState" {{ "appid" "{app}" "name" "Synthetic" "installdir" "{folder}" }}',
        encoding="utf-8",
    )
    return manifest


def _epic_manifest(
    directory: Path, installation: Path, name: str = "Synthetic"
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    manifest = directory / "synthetic.item"
    manifest.write_text(
        json.dumps({"InstallLocation": str(installation), "DisplayName": name}),
        encoding="utf-8",
    )
    return manifest


def _discover(
    steam_roots: tuple[Path, ...] = (),
    epic: Path | None = None,
    gog: tuple[tuple[object, object], ...] = (),
) -> discovery.DiscoveryResult:
    return service._discover(
        context.DiscoveryContext(lambda: False), _providers(steam_roots, epic, gog)
    )


def _providers(
    steam_roots: tuple[Path, ...] = (),
    epic: Path | None = None,
    gog: tuple[tuple[object, object], ...] = (),
) -> tuple[InstallationProvider, ...]:
    return (
        SteamProvider(lambda state: steam_roots),
        EpicProvider(lambda state: epic),
        GOGProvider(lambda state: gog),
    )


@pytest.mark.portable
def test_launcher_candidates_and_deduplication(tmp_path: Path) -> None:
    steam = tmp_path / "steam"
    other = tmp_path / "other library"
    game = other / "steamapps/common/Synthetic"
    game.mkdir(parents=True)
    primary = steam / "steamapps/common/Primary"
    primary.mkdir(parents=True)
    _steam_manifest(steam, "Primary")
    _steam_manifest(other, "Synthetic")
    config = steam / "config"
    config.mkdir()
    (config / "libraryfolders.vdf").write_text(
        f'"libraryfolders" {{ "0" {{ "path" "{_vdf_path(steam)}" }} '
        f'"1" {{ "path" "{_vdf_path(other)}" "apps" {{ "1" "123" }} }} }}',
        encoding="utf-8",
    )
    epic_dir = tmp_path / "epic"
    _epic_manifest(epic_dir, game)
    gog_game = tmp_path / "gog"
    gog_game.mkdir()
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    result = _discover((steam,), epic_dir, ((str(gog_game), "GOG synthetic"),))

    by_path = {candidate.path: candidate for candidate in result.candidates}
    assert set(by_path) == {primary, game, gog_game}
    assert by_path[game].sources == ("steam", "epic")
    assert by_path[gog_game].sources == ("gog",)
    assert all(c.availability == "available" for c in result.candidates)
    assert not result.issues
    assert not result.truncated
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


@pytest.mark.portable
def test_platform_neutral_discovery_uses_selected_providers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifests = tmp_path / "manifests"
    _epic_manifest(manifests, tmp_path)

    def selected() -> tuple[InstallationProvider, ...]:
        return (EpicProvider(lambda state: manifests), SteamProvider(), GOGProvider())

    monkeypatch.setattr(providers, "built_in_providers", selected)
    monkeypatch.setattr(service, "CURRENT_OS", OperatingSystem.LINUX)
    result = discovery.discover_installations()
    assert result.candidates == (
        discovery.Candidate(tmp_path, "Synthetic", ("epic",), "available"),
    )
    assert result.issues == (
        "Steam: automatic discovery unavailable on linux",
        "GOG: automatic discovery unavailable on linux",
    )
    assert not result.truncated


@pytest.mark.portable
def test_unsupported_platform_reports_discovery_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with monkeypatch.context() as patch:
        patch.setattr(service, "CURRENT_OS", OperatingSystem.UNKNOWN)
        result = discovery.discover_installations()
        assert not result.candidates
        assert len(result.issues) == 3
        assert all("unavailable" in issue for issue in result.issues)
        assert not result.truncated
        with pytest.raises(discovery.DiscoveryCancelled):
            discovery.discover_installations(cancelled=lambda: True)
    assert discovery.select_folder(tmp_path).candidates[0].availability == "available"


@pytest.mark.portable
def test_registry_adapter_accounts_for_failures_and_remaining_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = context.DiscoveryContext(lambda: False)
    monkeypatch.setattr(context, "_MAX_TOTAL_METADATA", 10)
    monkeypatch.setattr(_registry, "_MAX_REGISTRY_VALUE", 8)
    outcomes = iter(
        (
            SimpleNamespace(bytes_read=4, text="x", error=None, truncated=False),
            SimpleNamespace(
                bytes_read=0,
                text="",
                error=FileNotFoundError("missing"),
                truncated=False,
            ),
            SimpleNamespace(
                bytes_read=2, text="", error=ValueError("type"), truncated=False
            ),
            SimpleNamespace(
                bytes_read=4, text="", error=ValueError("read limit"), truncated=True
            ),
        )
    )
    limits: list[int] = []

    def read(key: object, name: str, max_bytes: int) -> SimpleNamespace:
        limits.append(max_bytes)
        return next(outcomes)

    monkeypatch.setattr(
        _registry,
        "windows_registry",
        SimpleNamespace(read_registry_text=read),
        raising=False,
    )
    assert _registry._registry_text(state, 0, "valid") == "x"
    with pytest.raises(FileNotFoundError):
        _registry._registry_text(state, 0, "missing")
    with pytest.raises(ValueError, match="type"):
        _registry._registry_text(state, 0, "wrong")
    with pytest.raises(ValueError, match="read limit"):
        _registry._registry_text(state, 0, "oversize")
    assert state.bytes_read == 10
    assert state.truncated
    with pytest.raises(context._LimitReached):
        _registry._registry_text(state, 0, "exhausted")
    assert limits == [8, 6, 6, 4]


@pytest.mark.portable
def test_steam_component_validation_uses_host_path_rules(tmp_path: Path) -> None:
    steam = tmp_path / "steam"
    _steam_manifest(steam, "CON")
    (steam / "steamapps/libraryfolders.vdf").write_text(
        '"libraryfolders" {}', encoding="utf-8"
    )
    if os.name != "nt":
        (steam / "steamapps/common/CON").mkdir(parents=True)

    result = _discover((steam,))
    if os.name == "nt":
        assert not result.candidates
        assert any(
            "invalid Steam installation folder" in issue for issue in result.issues
        )
    else:
        assert len(result.candidates) == 1
        assert result.candidates[0].path == steam / "steamapps/common/CON"
        assert result.candidates[0].availability == "available"
        assert not result.issues


@pytest.mark.portable
def test_legacy_steam_library_and_untrusted_folder(tmp_path: Path) -> None:
    steam = tmp_path / "steam"
    other = tmp_path / "other"
    game = other / "steamapps/common/Synthetic"
    game.mkdir(parents=True)
    _steam_manifest(steam, "../outside")
    _steam_manifest(other, "Synthetic")
    (steam / "steamapps/libraryfolders.vdf").write_text(
        f'"LibraryFolders" {{ // legacy format\n "1" "{_vdf_path(other)}" }}',
        encoding="utf-8",
    )

    result = _discover((steam,))

    assert [c.path for c in result.candidates] == [game]
    assert any("invalid Steam installation folder" in issue for issue in result.issues)


@pytest.mark.portable
def test_manual_folder_and_stale_candidates(tmp_path: Path) -> None:
    selected = discovery.select_folder(tmp_path)
    assert selected.candidates == (
        discovery.Candidate(tmp_path, tmp_path.name, ("manual",), "available"),
    )
    missing = tmp_path / "missing"
    result = _discover(gog=((str(missing), "Missing"), ("relative", "Invalid")))
    assert result.candidates[0].path == missing
    assert result.candidates[0].availability == "missing"
    assert len(result.candidates) == 1
    assert result.issues
    assert discovery.select_folder(missing).candidates[0].availability == "missing"


@pytest.mark.portable
def test_missing_malformed_and_unreadable_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    steam = tmp_path / "steam"
    bad_steam = _steam_manifest(steam, "Synthetic")
    bad_steam.write_text('"AppState" { "installdir"', encoding="utf-8")
    epic_dir = tmp_path / "epic"
    unreadable = _epic_manifest(epic_dir, tmp_path)
    malformed = epic_dir / "malformed.item"
    malformed.write_text("{", encoding="utf-8")
    original_open = Path.open

    def guarded_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path == unreadable:
            raise PermissionError("synthetic denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    result = _discover((steam,), epic_dir, ((None, "Missing registry path"),))

    assert not result.candidates
    assert any("libraryfolders.vdf" in issue for issue in result.issues)
    assert any(bad_steam.name in issue for issue in result.issues)
    assert any("synthetic denied" in issue for issue in result.issues)
    assert any(malformed.name in issue for issue in result.issues)
    assert any("invalid installation path" in issue for issue in result.issues)


@pytest.mark.portable
def test_discovery_metadata_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    epic = tmp_path / "epic"
    epic.mkdir()
    (epic / "oversize.item").write_bytes(b"x" * 33)
    monkeypatch.setattr(context, "_MAX_METADATA", 32)
    result = _discover(epic=epic)
    assert not result.candidates
    assert result.truncated
    assert any("read limit" in issue for issue in result.issues)

    for index in range(5):
        (epic / f"{index}.item").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(context, "_MAX_ENTRIES", 2)
    limited = _discover(epic=epic)
    assert limited.truncated
    assert any("budget exhausted" in issue for issue in limited.issues)


@pytest.mark.portable
def test_aggregate_budget_and_ambiguous_epic_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "duplicate.item").write_text(
        '{"InstallLocation": '
        + json.dumps(str(tmp_path))
        + ', "InstallLocation": '
        + json.dumps(str(manifests))
        + "}",
        encoding="utf-8",
    )
    result = _discover(epic=manifests)
    assert not result.candidates
    assert any("ambiguous" in issue for issue in result.issues)
    (manifests / "duplicate.item").unlink()
    for index in range(3):
        (manifests / f"{index}.item").write_text(" " * 8 + "{}", encoding="utf-8")
    monkeypatch.setattr(context, "_MAX_TOTAL_METADATA", 25)
    state = context.DiscoveryContext(lambda: False)
    limited = service._discover(state, _providers(epic=manifests))
    assert limited.truncated
    assert state.bytes_read <= 25
    assert any("read limit" in issue for issue in limited.issues)


@pytest.mark.portable
def test_entry_budget_is_shared_across_providers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    epic_game = tmp_path / "epic_game"
    gog_game = tmp_path / "gog_game"
    excluded = tmp_path / "excluded"
    for game in (epic_game, gog_game, excluded):
        game.mkdir()
    manifests = tmp_path / "manifests"
    _epic_manifest(manifests, epic_game)
    monkeypatch.setattr(context, "_MAX_ENTRIES", 2)

    result = _discover(
        epic=manifests,
        gog=((str(gog_game), "GOG"), (str(excluded), "Excluded")),
    )

    assert [(c.path, c.sources) for c in result.candidates] == [
        (epic_game, ("epic",)),
        (gog_game, ("gog",)),
    ]
    assert result.truncated
    assert any("budget exhausted" in issue for issue in result.issues)


@pytest.mark.portable
def test_traversal_and_invalid_encoding(tmp_path: Path) -> None:
    game = tmp_path / "game"
    game.mkdir()
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "invalid.item").write_bytes(b"\xff")
    result = _discover(
        epic=manifests,
        gog=(
            (str(game / ".." / "game"), "Traversal"),
            (str(game) + "\ud800", "Invalid"),
        ),
    )
    assert not result.candidates
    assert len(result.issues) == 3


@pytest.mark.portable
def test_discovery_does_not_open_installation_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    game = tmp_path / "game"
    game.mkdir()
    asset = game / "asset.ast"
    asset.write_bytes(b"STRM" + b"x" * 128)
    epic = tmp_path / "epic"
    _epic_manifest(epic, game)
    original_open = Path.open

    def guarded_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        assert not path.is_relative_to(game)
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", guarded_open)
        result = _discover(epic=epic)
        assert result.candidates[0].path == game
        assert discovery.select_folder(game).candidates[0].path == game
    assert asset.read_bytes() == b"STRM" + b"x" * 128


@pytest.mark.portable
def test_probe_signature_is_provisional_and_reads_only_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "native.bin"
    source.write_bytes(b"STRM" + b"x" * 128)
    fake = tmp_path / "fake.ast"
    fake.write_bytes(b"nope")
    deep = tmp_path / "one/two/three"
    deep.mkdir(parents=True)
    outside_sample = deep / "other.ast"
    outside_sample.write_bytes(b"STRM")
    candidate = discovery.select_folder(tmp_path).candidates[0]
    original_open = Path.open
    reads: list[int] = []

    class Reader:
        def __init__(self, stream: Any) -> None:
            self.stream = stream

        def __enter__(self) -> Reader:
            return self

        def __exit__(self, *args: Any) -> None:
            self.stream.close()

        def read(self, size: int) -> bytes:
            reads.append(size)
            data: bytes = self.stream.read(size)
            return data

    def tracked_open(path: Path, mode: str = "r", *args: Any, **kwargs: Any) -> Reader:
        assert path != outside_sample
        assert mode == "rb"
        assert kwargs.get("buffering") == 0
        return Reader(original_open(path, mode, *args, **kwargs))

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", tracked_open)
        probe = discovery.probe_installation(candidate)
    assert probe.ast_signature
    assert probe.truncated
    assert reads == [4, 4]
    assert source.read_bytes() == b"STRM" + b"x" * 128
    assert fake.read_bytes() == b"nope"
    assert outside_sample.read_bytes() == b"STRM"


@pytest.mark.portable
def test_probe_reports_unreadable_and_disappeared_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = tmp_path / "asset.bin"
    asset.write_bytes(b"STRM")
    candidate = discovery.select_folder(tmp_path).candidates[0]
    original_open = Path.open

    def guarded_open(path: Path, *args: Any, **kwargs: Any) -> Any:
        if path == asset:
            raise PermissionError("synthetic denied")
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", guarded_open)
        result = discovery.probe_installation(candidate)
    assert not result.ast_signature
    assert result.truncated
    assert result.issues
    asset.unlink()
    moved = tmp_path / "moved"
    moved.mkdir()
    candidate = discovery.select_folder(moved).candidates[0]
    moved.rmdir()
    result = discovery.probe_installation(candidate)
    assert result.truncated
    assert result.issues


@pytest.mark.portable
def test_probe_skips_reparse_points_and_special_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    game = tmp_path / "game"
    game.mkdir()
    linked = game / "linked"
    linked.mkdir()
    (linked / "hidden.ast").write_bytes(b"STRM")
    special = game / "special"
    special.write_bytes(b"STRM")
    candidate = discovery.select_folder(game).candidates[0]
    original_lstat = Path.lstat

    def observed_lstat(path: Path) -> os.stat_result:
        info = original_lstat(path)
        if path == linked:
            return cast(
                os.stat_result,
                SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400),
            )
        if path == special:
            return cast(
                os.stat_result,
                SimpleNamespace(st_mode=stat.S_IFIFO, st_file_attributes=0),
            )
        return info

    monkeypatch.setattr(Path, "lstat", observed_lstat)
    result = discovery.probe_installation(candidate)
    assert result.truncated
    assert not result.ast_signature
    assert result.entries_examined == 2


@pytest.mark.portable
def test_probe_entry_budget_and_no_extension_based_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index in range(8):
        (tmp_path / f"{index}.ast").write_bytes(b"nope")
    candidate = discovery.select_folder(tmp_path).candidates[0]
    monkeypatch.setattr(probe, "_MAX_PROBE_ENTRIES", 3)
    result = discovery.probe_installation(candidate)
    assert result.entries_examined == 3
    assert result.truncated
    assert not result.ast_signature


@pytest.mark.portable
def test_cancellation_during_discovery_and_probe(tmp_path: Path) -> None:
    for index in range(5):
        (tmp_path / f"{index}.item").write_text("{}", encoding="utf-8")
    candidate = discovery.select_folder(tmp_path).candidates[0]
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks > 3

    with pytest.raises(discovery.DiscoveryCancelled):
        service._discover(
            context.DiscoveryContext(cancelled), _providers(epic=tmp_path)
        )
    checks = 0
    with pytest.raises(discovery.DiscoveryCancelled):
        discovery.probe_installation(candidate, cancelled=cancelled)
    with pytest.raises(discovery.DiscoveryCancelled):
        discovery.select_folder(tmp_path, cancelled=lambda: True)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows registry boundary")
@pytest.mark.parametrize("is_64bit", [False, True], ids=["32-bit", "64-bit"])
def test_windows_discovery_registry_and_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, is_64bit: bool
) -> None:
    import winreg

    if is_64bit:
        view = winreg.KEY_WOW64_64KEY
        steam_hive = winreg.HKEY_LOCAL_MACHINE
        steam_value = "InstallPath"
        gog_hive = winreg.HKEY_CURRENT_USER
    else:
        view = winreg.KEY_WOW64_32KEY
        steam_hive = winreg.HKEY_CURRENT_USER
        steam_value = "SteamPath"
        gog_hive = winreg.HKEY_LOCAL_MACHINE

    steam = tmp_path / "steam"
    steam_game = steam / "steamapps/common/Synthetic"
    steam_game.mkdir(parents=True)
    _steam_manifest(steam, "Synthetic")
    (steam / "steamapps/libraryfolders.vdf").write_text(
        '"libraryfolders" {}', encoding="utf-8"
    )
    epic_game = tmp_path / "epic"
    epic_game.mkdir()
    epic_dir = tmp_path / "Epic/EpicGamesLauncher/Data/Manifests"
    _epic_manifest(epic_dir, epic_game)
    gog_game = tmp_path / "gog"
    gog_game.mkdir()

    class Key:
        def __init__(self, kind: str) -> None:
            self.kind = kind

        def __enter__(self) -> Key:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    def open_key(hive: object, name: str, reserved: int, access: int) -> Key:
        assert not access & (winreg.KEY_SET_VALUE | winreg.KEY_CREATE_SUB_KEY)
        if not access & view:
            raise FileNotFoundError(name)
        if hive == steam_hive and name == r"Software\Valve\Steam":
            return Key("steam")
        if hive == gog_hive and name == r"Software\GOG.com\Games":
            return Key("gog")
        if isinstance(hive, Key) and hive.kind == "gog" and name == "1":
            return Key("game")
        raise FileNotFoundError(name)

    def query_value(state: context.DiscoveryContext, key: Key, name: str) -> str:
        values = {
            ("steam", steam_value): str(steam),
            ("game", "path"): str(gog_game),
            ("game", "gameName"): "Synthetic GOG",
        }
        return values[key.kind, name]

    monkeypatch.setattr(winreg, "OpenKey", open_key)
    monkeypatch.setattr(_registry, "_registry_text", query_value)
    monkeypatch.setattr(winreg, "QueryInfoKey", lambda key: (1, 0, 0))
    monkeypatch.setattr(winreg, "EnumKey", lambda key, index: "1")
    monkeypatch.setenv("ProgramData", str(tmp_path))
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)

    result = discovery.discover_installations()
    assert discovery.discover_windows() == result

    assert {c.path: c.sources for c in result.candidates} == {
        steam_game: ("steam",),
        epic_game: ("epic",),
        gog_game: ("gog",),
    }
    assert not result.issues


@pytest.mark.skipif(sys.platform != "win32", reason="Windows registry boundary")
@pytest.mark.parametrize(
    ("status", "kind", "data", "expected_error", "charged", "truncated"),
    [
        (0, 1, "Synthetic \u03b1\x00".encode("utf-16-le"), None, 24, False),
        (234, 1, b"", ValueError, 64, True),
        (2, 1, b"", FileNotFoundError, 0, False),
        (5, 1, b"", OSError, 64, False),
        (0, 3, b"data", ValueError, 4, False),
        (0, 1, b"\x00", UnicodeError, 1, False),
        (0, 1, b"a\x00\x00\x00b\x00", ValueError, 6, False),
    ],
)
def test_registry_reader_bounds_simulated_native_values(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    kind: int,
    data: bytes,
    expected_error: type[Exception] | None,
    charged: int,
    truncated: bool,
) -> None:
    import ctypes
    from ctypes import wintypes

    from muteinous.infrastructure.platform import windows_registry

    # Replace the native API before invoking the real reader. No registry
    # handles are opened, and no keys or values are created or changed.
    def query(
        key: Any,
        name: str,
        reserved: Any,
        value_type: Any,
        buffer: Any,
        size: Any,
    ) -> int:
        assert name == "fixture"
        size_field = ctypes.cast(size, ctypes.POINTER(wintypes.DWORD)).contents
        assert size_field.value == ctypes.sizeof(buffer) == 64
        if status == 234:
            # Report a much larger required buffer; the reader must not retry.
            size_field.value = 4096
        elif status == 0:
            kind_field = ctypes.cast(value_type, ctypes.POINTER(wintypes.DWORD))
            kind_field.contents.value = kind
            ctypes.memmove(buffer, data, len(data))
            size_field.value = len(data)
        return status

    native_query = Mock(side_effect=query)
    loader = Mock(return_value=SimpleNamespace(RegQueryValueExW=native_query))
    monkeypatch.setattr(ctypes, "WinDLL", loader)
    result = windows_registry.read_registry_text(0, "fixture", 64)

    loader.assert_called_once_with("advapi32.dll")
    native_query.assert_called_once()
    assert result.bytes_read == charged
    assert result.truncated is truncated
    if expected_error is None:
        assert result.error is None
        assert result.text == "Synthetic \u03b1"
    else:
        assert isinstance(result.error, expected_error)
        assert not result.text
