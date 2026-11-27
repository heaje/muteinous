"""Synthetic launcher metadata and bounded read-only probing contracts."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from muteinous.plugins.video_games import discovery


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
    return discovery._discover(
        discovery._Discovery(lambda: False), steam_roots, epic, gog
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
    monkeypatch.setattr(discovery, "_MAX_METADATA", 32)
    result = _discover(epic=epic)
    assert not result.candidates
    assert result.truncated
    assert any("read limit" in issue for issue in result.issues)

    for index in range(5):
        (epic / f"{index}.item").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(discovery, "_MAX_ENTRIES", 2)
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
        '{"InstallLocation": ' + json.dumps(str(tmp_path))
        + ', "InstallLocation": ' + json.dumps(str(manifests)) + "}",
        encoding="utf-8",
    )
    result = _discover(epic=manifests)
    assert not result.candidates
    assert any("ambiguous" in issue for issue in result.issues)
    (manifests / "duplicate.item").unlink()
    for index in range(3):
        (manifests / f"{index}.item").write_text(" " * 8 + "{}", encoding="utf-8")
    monkeypatch.setattr(discovery, "_MAX_TOTAL_METADATA", 25)
    state = discovery._Discovery(lambda: False)
    limited = discovery._discover(state, (), manifests, ())
    assert limited.truncated
    assert state.bytes_read <= 25
    assert any("read limit" in issue for issue in limited.issues)


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
            return os.stat_result((stat.S_IFIFO, *tuple(info)[1:]))
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
    monkeypatch.setattr(discovery, "_MAX_PROBE_ENTRIES", 3)
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
        discovery._discover(discovery._Discovery(cancelled), (), tmp_path, ())
    checks = 0
    with pytest.raises(discovery.DiscoveryCancelled):
        discovery.probe_installation(candidate, cancelled=cancelled)
    with pytest.raises(discovery.DiscoveryCancelled):
        discovery.select_folder(tmp_path, cancelled=lambda: True)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows registry boundary")
def test_windows_discovery_registry_and_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import winreg

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
        if (
            hive == winreg.HKEY_CURRENT_USER
            and name == r"Software\Valve\Steam"
            and access & winreg.KEY_WOW64_32KEY
        ):
            return Key("steam")
        if (
            hive == winreg.HKEY_LOCAL_MACHINE
            and name == r"Software\GOG.com\Games"
            and access & winreg.KEY_WOW64_32KEY
        ):
            return Key("gog")
        if isinstance(hive, Key) and hive.kind == "gog" and name == "1":
            return Key("game")
        raise FileNotFoundError(name)

    def query_value(state: discovery._Discovery, key: Key, name: str) -> str:
        values = {
            ("steam", "SteamPath"): str(steam),
            ("game", "path"): str(gog_game),
            ("game", "gameName"): "Synthetic GOG",
        }
        return values[key.kind, name]

    monkeypatch.setattr(winreg, "OpenKey", open_key)
    monkeypatch.setattr(discovery, "_registry_text", query_value)
    monkeypatch.setattr(winreg, "QueryInfoKey", lambda key: (1, 0, 0))
    monkeypatch.setattr(winreg, "EnumKey", lambda key, index: "1")
    monkeypatch.setenv("ProgramData", str(tmp_path))
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)

    result = discovery.discover_windows()

    assert {c.path: c.sources for c in result.candidates} == {
        steam_game: ("steam",),
        epic_game: ("epic",),
        gog_game: ("gog",),
    }
    assert not result.issues


@pytest.mark.skipif(sys.platform != "win32", reason="Windows registry boundary")
def test_registry_reader_bounds_real_synthetic_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import winreg

    key_path = rf"Software\MuteinousTests-{uuid4().hex}"
    monkeypatch.setattr(discovery, "_MAX_REGISTRY_VALUE", 64)
    state = discovery._Discovery(lambda: False)
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ | winreg.KEY_WRITE
        ) as key:
            winreg.SetValueEx(key, "valid", 0, winreg.REG_SZ, "Synthetic \u03b1")
            winreg.SetValueEx(key, "oversize", 0, winreg.REG_SZ, "x" * 64)
            winreg.SetValueEx(key, "wrong", 0, winreg.REG_BINARY, b"data")
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ
        ) as key:
            assert discovery._registry_text(state, key, "valid") == "Synthetic \u03b1"
            before = state.bytes_read
            with pytest.raises(ValueError, match="read limit"):
                discovery._registry_text(state, key, "oversize")
            assert state.truncated
            assert state.bytes_read == before + 64
            with pytest.raises(ValueError, match="type"):
                discovery._registry_text(state, key, "wrong")
            with pytest.raises(FileNotFoundError):
                discovery._registry_text(state, key, "missing")
    finally:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
