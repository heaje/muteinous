"""Project-owned release boundaries, with no external process execution."""

import json
import platform
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import release

SHA = "a" * 40
OTHER_SHA = "b" * 40
TAG = "v0.2.0rc1"
pytestmark = pytest.mark.portable


@pytest.fixture(autouse=True)
def prohibit_subprocesses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess, "run", Mock(side_effect=AssertionError("external process"))
    )


@pytest.mark.parametrize(
    ("head", "shallow", "status", "error"),
    [
        (SHA, "false", "", None),
        (OTHER_SHA, "false", "", "requested source SHA"),
        (SHA, "true", "", "Full Git history"),
        (SHA, "false", "?? untracked", "dirty"),
    ],
)
def test_validate_source(
    monkeypatch: pytest.MonkeyPatch,
    head: str,
    shallow: str,
    status: str,
    error: str | None,
) -> None:
    responses = {
        ("rev-parse", "HEAD"): head,
        ("rev-parse", "--is-shallow-repository"): shallow,
        ("status", "--porcelain", "--untracked-files=normal"): status,
    }

    def git(*args: str) -> str:
        return responses[args]

    monkeypatch.setattr(release, "git", git)
    if error is None:
        release.validate_source(SHA)
    else:
        with pytest.raises(RuntimeError, match=error):
            release.validate_source(SHA)


@pytest.mark.parametrize("state", ["missing", "bootstrap", "valid", "invalid"])
def test_release_history_boundary(monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    bootstrap = release.BOOTSTRAP
    head = bootstrap if state == "bootstrap" else SHA
    history = {
        "missing": SHA,
        "bootstrap": bootstrap,
        "valid": f"{SHA}\n{bootstrap}\n{OTHER_SHA}",
        "invalid": f"{SHA}\n{bootstrap}\n{OTHER_SHA}",
    }[state]
    responses: dict[tuple[str, ...], str] = {
        ("rev-list", "HEAD"): history,
        ("rev-parse", "HEAD"): head,
    }

    def git(*args: str) -> str:
        return responses[args]

    cz = Mock(
        return_value="",
        side_effect=RuntimeError("commitizen") if state == "invalid" else None,
    )
    monkeypatch.setattr(release, "git", git)
    monkeypatch.setattr(release, "cz", cz)
    if state == "missing":
        with pytest.raises(RuntimeError, match="bootstrap commit"):
            release.check_history()
    elif state == "invalid":
        with pytest.raises(RuntimeError, match="commitizen"):
            release.check_history()
    else:
        release.check_history()
    if state in {"missing", "bootstrap"}:
        cz.assert_not_called()
    else:
        cz.assert_called_once_with("check", "--rev-range", f"{bootstrap}..HEAD")


def test_divergent_release_tag_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release, "local_tags", lambda: {"v0.1.0": OTHER_SHA})
    git = Mock(side_effect=RuntimeError("merge-base"))
    cz = Mock()
    monkeypatch.setattr(release, "git", git)
    monkeypatch.setattr(release, "cz", cz)
    with pytest.raises(RuntimeError, match="merge-base"):
        release.propose("stable")
    git.assert_called_once_with("merge-base", "--is-ancestor", "v0.1.0", "HEAD")
    cz.assert_not_called()


def test_notes_use_last_stable_and_hide_prerelease_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git = Mock(return_value="")
    cz = Mock(return_value="Release notes")
    monkeypatch.setattr(release, "git", git)
    monkeypatch.setattr(release, "cz", cz)
    assert release.notes(TAG, ["v0.1.0", "v0.2.0a1", "v0.0.9"]) == "Release notes"
    git.assert_called_once_with("tag", "-d", "v0.2.0a1")
    cz.assert_called_once_with(
        "changelog", "--dry-run", "--unreleased-version", TAG, "--start-rev", "v0.1.0"
    )


def test_notes_refuse_empty_provider_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(release, "cz", lambda *_: "")
    with pytest.raises(RuntimeError, match="empty release notes"):
        release.notes(TAG, [])


@pytest.mark.parametrize("tag", [None, TAG], ids=["development", "release"])
def test_build_records_artifact_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tag: str | None
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(release, "validate_source", lambda sha: None)
    monkeypatch.setattr(release, "git", lambda *_: SHA)
    monkeypatch.setattr(platform, "platform", lambda: "test-platform")
    monkeypatch.setattr(platform, "machine", lambda: "test-machine")
    (tmp_path / "uv.lock").write_bytes(b"synthetic lock")
    version = tag[1:] if tag else "0.2.0.dev1"
    wheel_name = f"muteinous-{version}-py3-none-any.whl"
    sdist_name = f"muteinous-{version}.tar.gz"

    def run(*args: str) -> str:
        if args == (sys.executable, "-m", "setuptools_scm"):
            return version
        if args == (sys.executable, "scripts/check_package.py"):
            dist = tmp_path / "dist"
            dist.mkdir()
            (dist / wheel_name).write_bytes(b"synthetic wheel")
            (dist / sdist_name).write_bytes(b"synthetic sdist")
            return "synthetic build"
        if args == ("uv", "--version"):
            return "uv test"
        pytest.fail(f"Unexpected external command: {args}")

    monkeypatch.setattr(release, "run", run)
    output = tmp_path / "artifacts"
    previous = {"v0.2.0a1": SHA}
    if tag:
        release.build(
            SHA,
            output,
            tag,
            source_tags=previous,
            release_notes="Release notes",
            channel="rc",
        )
        assert release.validate_artifacts(output, SHA, "rc") == (tag, previous)
        assert (output / "release-notes.md").read_text("utf-8") == "Release notes\n"
    else:
        release.build(SHA, output)
    metadata = json.loads((output / "build-metadata.json").read_text("utf-8"))
    assert metadata["sha"] == SHA
    assert metadata["tag"] == tag
    assert metadata["version"] == version
    assert metadata["environment"]["lock_sha256"] == release.digest(
        tmp_path / "uv.lock"
    )
    assert metadata["artifacts"] == {
        name: release.digest(output / name) for name in (wheel_name, sdist_name)
    }
    for line in (output / "SHA256SUMS").read_text("utf-8").splitlines():
        expected, name = line.split("  ", 1)
        assert release.digest(output / name) == expected


@pytest.mark.parametrize(
    ("target", "version", "error"),
    [(OTHER_SHA, TAG[1:], "does not resolve"), (SHA, "0.2.0a1", "does not match")],
)
def test_build_rejects_wrong_tag_or_scm_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    version: str,
    error: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(release, "validate_source", lambda _: None)
    git = Mock(return_value=target)
    monkeypatch.setattr(release, "git", git)

    def run(*args: str) -> str:
        assert args == (sys.executable, "-m", "setuptools_scm")
        return version

    monkeypatch.setattr(release, "run", run)
    output = tmp_path / "artifacts"
    with pytest.raises(RuntimeError, match=error):
        release.build(SHA, output, TAG)
    git.assert_called_once_with("rev-parse", f"{TAG}^{{commit}}")
    assert not output.exists()
    assert not (tmp_path / "dist").exists()


@pytest.mark.parametrize("stale_name", ["dist", "artifacts"])
def test_build_refuses_stale_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stale_name: str
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(release, "validate_source", lambda _: None)
    stale = tmp_path / stale_name
    stale.mkdir()
    marker = stale / "existing"
    marker.write_bytes(b"keep")
    with pytest.raises(RuntimeError, match="fresh output"):
        release.build(SHA, tmp_path / "artifacts")
    assert marker.read_bytes() == b"keep"


def test_prepare_refuses_remote_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(release, "validate_source", lambda _: None)
    monkeypatch.setattr(release, "check_history", lambda: None)
    monkeypatch.setattr(release, "local_tags", dict)
    monkeypatch.setattr(release, "remote_tags", lambda: {"v0.1.0": SHA})
    propose = Mock()
    monkeypatch.setattr(release, "propose", propose)
    output = tmp_path / "artifacts"
    with pytest.raises(RuntimeError, match="Remote tags changed"):
        release.prepare(SHA, "rc", output)
    propose.assert_not_called()
    assert not output.exists()
