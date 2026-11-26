"""Release workflow safety tests using controlled GitHub API fakes."""

import json
import time
import tomllib
from pathlib import Path
from typing import Any

import pytest

from scripts import release

SHA = "a" * 40
OTHER_SHA = "b" * 40
TAG = "v0.2.0a1"
pytestmark = pytest.mark.portable


@pytest.mark.parametrize(
    ("tag", "channel", "existing", "message"),
    [
        ("v1.0.0", "stable", [], "reviewed policy"),
        ("v1.0.0a1", "alpha", [], "reviewed policy"),
        (TAG, "alpha", [TAG], "already exists"),
        ("v0.2.0a1", "alpha", ["v0.2.0b1"], "Non-increasing"),
        ("v0.2.0b1", "alpha", [], "not the requested"),
        ("v0.02.0", "stable", [], "Noncanonical"),
        ("v0.2.0.dev1", "stable", [], "Noncanonical"),
    ],
)
def test_candidate_guards(
    tag: str, channel: str, existing: list[str], message: str
) -> None:
    with pytest.raises(RuntimeError, match=message):
        release.validate_candidate(tag, channel, existing)


def test_versioning_configuration() -> None:
    root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))
    cz = config["tool"]["commitizen"]
    assert cz["name"] == "cz_conventional_commits"
    assert cz["version_provider"] == "scm"
    assert cz["tag_format"] == "v$version"
    assert cz["version_scheme"] == "pep440"
    assert cz["major_version_zero"] is True
    assert cz["allowed_prefixes"] == []
    assert "version" in config["project"]["dynamic"]
    assert "version" not in config["project"]


@pytest.mark.parametrize(
    ("channel", "version"),
    [
        ("alpha", "0.2.0a1"),
        ("beta", "0.2.0b1"),
        ("rc", "0.2.0rc1"),
        ("stable", "0.2.0"),
    ],
)
def test_propose_requests_channel_without_mutating_tags(
    monkeypatch: pytest.MonkeyPatch, channel: str, version: str
) -> None:
    tags = {"v0.1.0": SHA}
    monkeypatch.setattr(release, "local_tags", lambda: dict(tags))

    def git(*args: str) -> str:
        assert args == ("merge-base", "--is-ancestor", "v0.1.0", "HEAD")
        return ""

    def cz(*args: str) -> str:
        expected: tuple[str, ...] = ("bump", "--get-next", "--yes")
        if channel != "stable":
            expected += ("--prerelease", channel, "--prerelease-offset", "1")
        assert args == expected
        return version

    monkeypatch.setattr(release, "git", git)
    monkeypatch.setattr(release, "cz", cz)
    assert release.propose(channel) == f"v{version}"


def test_propose_rejects_wrong_channel_from_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(release, "local_tags", dict)
    monkeypatch.setattr(release, "cz", lambda *_: "0.2.0b1")
    with pytest.raises(RuntimeError, match="not the requested alpha"):
        release.propose("alpha")


def artifacts(
    output: Path,
    tag: str,
    channel: str,
    source_tags: dict[str, str] | None = None,
) -> None:
    """Make synthetic transfer files; real builds are tested in test_versioning."""
    output.mkdir()
    wheel = output / f"muteinous-{tag[1:]}-py3-none-any.whl"
    sdist = output / f"muteinous-{tag[1:]}.tar.gz"
    wheel.write_bytes(b"wheel contents")
    sdist.write_bytes(b"source contents")
    notes = output / "release-notes.md"
    notes.write_text("# Release notes", encoding="utf-8")
    metadata = {
        "package": "muteinous",
        "sha": SHA,
        "tag": tag,
        "version": tag[1:],
        "channel": channel,
        "source_tags": source_tags or {},
        "notes_sha256": release.digest(notes),
        "artifacts": {p.name: release.digest(p) for p in (wheel, sdist)},
    }
    (output / "build-metadata.json").write_text(
        json.dumps(metadata) + "\n", encoding="utf-8", newline="\n"
    )
    release.write_checksums(output)


@pytest.mark.parametrize(
    ("channel", "tag"),
    [
        ("alpha", "v0.2.0a1"),
        ("beta", "v0.2.0b1"),
        ("rc", "v0.2.0rc1"),
        ("stable", "v0.2.0"),
    ],
)
@pytest.mark.parametrize("digest_state", ["valid", "missing", "wrong"])
def test_only_draft_is_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    channel: str,
    tag: str,
    digest_state: str,
) -> None:
    output = tmp_path / "artifacts"
    artifacts(output, tag, channel)
    tags: dict[str, str] = {}
    records: list[dict[str, Any]] = []
    calls: list[tuple[str, ...]] = []

    def gh(*args: str) -> str:
        calls.append(args)
        assert args[:4] == ("gh", "release", "create", tag)
        assert "--draft" in args and "--target" in args
        assert args[args.index("--target") + 1] == SHA
        assert "--verify-tag" not in args
        assert ("--prerelease" in args) == (channel != "stable")
        assert args[args.index("--notes-file") + 1] == str(output / "release-notes.md")
        assets = [p for p in output.iterdir() if p.name != "release-notes.md"]
        assert all(str(asset) in args for asset in assets)
        records.append(
            {
                "tag_name": tag,
                "draft": True,
                "prerelease": channel != "stable",
                "target_commitish": SHA,
                "published_at": None,
                "assets": [
                    {
                        "name": p.name,
                        "size": p.stat().st_size,
                        "state": "uploaded",
                        "digest": {
                            "valid": f"sha256:{release.digest(p)}",
                            "missing": None,
                            "wrong": f"sha256:{'0' * 64}",
                        }[digest_state],
                    }
                    for p in assets
                ],
            }
        )
        return "draft URL"

    monkeypatch.setattr(time, "sleep", lambda _: None)
    monkeypatch.setattr(release, "validate_source", lambda _: None)
    monkeypatch.setattr(release, "local_tags", lambda: dict(tags))
    monkeypatch.setattr(release, "remote_tags", lambda: dict(tags))
    monkeypatch.setattr(release, "releases", lambda: list(records))
    monkeypatch.setattr(release, "run", gh)
    if digest_state == "valid":
        release.publish_draft(SHA, channel, output)
    else:
        with pytest.raises(
            RuntimeError, match="GitHub asset digest missing or mismatched"
        ):
            release.publish_draft(SHA, channel, output)
    # A single gh release create makes the draft; GitHub creates no tag yet.
    assert len(calls) == 1
    assert tags == {}
    assert not any("release" in call and "edit" in call for call in calls)


@pytest.mark.parametrize(
    ("filename", "message"),
    [
        ("muteinous-0.2.0a1-py3-none-any.whl", "Distribution checksum"),
        ("release-notes.md", "notes checksum"),
        ("SHA256SUMS", "manifest mismatch"),
    ],
)
def test_transferred_artifact_tampering_is_rejected(
    tmp_path: Path, filename: str, message: str
) -> None:
    output = tmp_path / "artifacts"
    artifacts(output, TAG, "alpha")
    (output / filename).write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match=message):
        release.validate_artifacts(output, SHA, "alpha")


def test_remote_tag_drift_prevents_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "artifacts"
    artifacts(output, TAG, "alpha")
    monkeypatch.setattr(release, "validate_source", lambda _: None)
    monkeypatch.setattr(release, "local_tags", dict)
    monkeypatch.setattr(release, "remote_tags", lambda: {TAG: SHA})
    monkeypatch.setattr(release, "run", lambda *_: pytest.fail("unexpected write"))
    with pytest.raises(RuntimeError, match="Tag already exists remotely"):
        release.publish_draft(SHA, "alpha", output)


@pytest.mark.parametrize("target", [OTHER_SHA, None])
def test_draft_target_must_match_validated_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target: str | None
) -> None:
    output = tmp_path / "artifacts"
    artifacts(output, TAG, "alpha")
    records: list[dict[str, Any]] = []

    def gh(*args: str) -> str:
        assets = [p for p in output.iterdir() if p.name != "release-notes.md"]
        records.append(
            {
                "tag_name": TAG,
                "draft": True,
                "prerelease": True,
                "published_at": None,
                "target_commitish": target,
                "assets": [
                    {
                        "name": p.name,
                        "size": p.stat().st_size,
                        "state": "uploaded",
                        "digest": f"sha256:{release.digest(p)}",
                    }
                    for p in assets
                ],
            }
        )
        return "draft URL"

    monkeypatch.setattr(time, "sleep", lambda _: None)
    monkeypatch.setattr(release, "validate_source", lambda _: None)
    monkeypatch.setattr(release, "local_tags", dict)
    monkeypatch.setattr(release, "remote_tags", dict)
    monkeypatch.setattr(release, "releases", lambda: list(records))
    monkeypatch.setattr(release, "run", gh)
    with pytest.raises(RuntimeError, match="targeting the validated SHA"):
        release.publish_draft(SHA, "alpha", output)


def test_duplicate_same_tag_drafts_fail_settled_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "artifacts"
    artifacts(output, TAG, "alpha")
    records: list[dict[str, Any]] = []

    def gh(*args: str) -> str:
        assets = [p for p in output.iterdir() if p.name != "release-notes.md"]
        record = {
            "tag_name": TAG,
            "draft": True,
            "prerelease": True,
            "published_at": None,
            "target_commitish": SHA,
            "assets": [
                {
                    "name": p.name,
                    "size": p.stat().st_size,
                    "state": "uploaded",
                    "digest": f"sha256:{release.digest(p)}",
                }
                for p in assets
            ],
        }
        records.extend([record, dict(record)])
        return "draft URL"

    monkeypatch.setattr(time, "sleep", lambda _: None)
    monkeypatch.setattr(release, "validate_source", lambda _: None)
    monkeypatch.setattr(release, "local_tags", dict)
    monkeypatch.setattr(release, "remote_tags", dict)
    monkeypatch.setattr(release, "releases", lambda: list(records))
    monkeypatch.setattr(release, "run", gh)
    with pytest.raises(RuntimeError, match="did not settle"):
        release.publish_draft(SHA, "alpha", output)


def test_tag_drift_during_draft_preflight_prevents_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "artifacts"
    artifacts(output, TAG, "alpha")
    remote = iter([{}, {"v0.1.0": OTHER_SHA}])
    writes: list[tuple[str, ...]] = []

    def track_write(*args: str) -> str:
        writes.append(args)
        return ""

    monkeypatch.setattr(release, "validate_source", lambda _: None)
    monkeypatch.setattr(release, "local_tags", dict)
    monkeypatch.setattr(release, "remote_tags", lambda: next(remote))
    monkeypatch.setattr(release, "releases", list)
    monkeypatch.setattr(release, "run", track_write)
    with pytest.raises(RuntimeError, match="Remote tags changed"):
        release.publish_draft(SHA, "alpha", output)
    assert not writes


@pytest.mark.parametrize("draft_tag", [TAG, "v0.1.0"])
def test_any_existing_draft_refuses_new_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    draft_tag: str,
) -> None:
    output = tmp_path / "artifacts"
    prior_tags = {"v0.1.0": OTHER_SHA}
    artifacts(output, TAG, "alpha", prior_tags)
    monkeypatch.setattr(release, "validate_source", lambda _: None)
    monkeypatch.setattr(release, "local_tags", lambda: prior_tags)
    monkeypatch.setattr(release, "remote_tags", lambda: prior_tags)
    monkeypatch.setattr(
        release,
        "releases",
        lambda: [{"tag_name": draft_tag, "draft": True}],
    )
    monkeypatch.setattr(release, "run", lambda *_: pytest.fail("unexpected write"))
    with pytest.raises(RuntimeError, match="Draft release"):
        release.publish_draft(SHA, "alpha", output)


def test_remote_tag_mismatch_refuses_new_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "artifacts"
    artifacts(output, TAG, "alpha")
    monkeypatch.setattr(release, "validate_source", lambda _: None)
    monkeypatch.setattr(release, "local_tags", lambda: {})
    monkeypatch.setattr(release, "remote_tags", lambda: {"v0.1.0": OTHER_SHA})
    monkeypatch.setattr(release, "run", lambda *_: pytest.fail("unexpected write"))
    with pytest.raises(RuntimeError, match="Remote tags changed"):
        release.publish_draft(SHA, "alpha", output)


def test_existing_release_tag_refuses_new_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "artifacts"
    artifacts(output, TAG, "alpha")
    monkeypatch.setattr(release, "validate_source", lambda _: None)
    monkeypatch.setattr(release, "local_tags", lambda: {})
    monkeypatch.setattr(release, "remote_tags", lambda: {TAG: SHA})
    monkeypatch.setattr(release, "releases", list)
    monkeypatch.setattr(release, "run", lambda *_: pytest.fail("unexpected write"))
    with pytest.raises(RuntimeError, match="Tag already exists remotely"):
        release.publish_draft(SHA, "alpha", output)


def test_release_tag_inventory_must_match_releases() -> None:
    release.check_release_inventory([], [])
    with pytest.raises(RuntimeError, match="inventory differs"):
        release.check_release_inventory(["v0.1.0"], [])
    with pytest.raises(RuntimeError, match="inventory differs"):
        release.check_release_inventory([], [{"tag_name": "v0.1.0"}])


def test_workflow_contracts() -> None:
    root = Path(__file__).resolve().parents[2] / ".github/workflows"
    workflows = {path.name: path.read_text("utf-8") for path in root.glob("*.yml")}
    for name in ("development-build.yml", "release.yml"):
        assert "workflow_dispatch" in workflows[name]
        assert "pull_request" not in workflows[name] and "push:" not in workflows[name]
    assert "muteinous-official-release" in workflows["release.yml"]
    assert "actions: read" not in workflows["release.yml"]
    assert "--draft" in (root.parent.parent / "scripts/release.py").read_text("utf-8")
    assert "--cleanup-tag" not in "".join(workflows.values())
    assert "gh release edit" not in "".join(workflows.values())
    assert "timeout-minutes: 10" in workflows["pr.yml"]
    assert "muteinous-official-release" in workflows["release.yml"]


def test_write_commands_refuse_to_run_outside_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(release, "run", lambda *_: pytest.fail("unexpected write"))
    for argv in (["draft", "--sha", SHA, "--output", "x", "--channel", "alpha"],):
        monkeypatch.setattr("sys.argv", ["release.py", *argv])
        with pytest.raises(SystemExit, match="only run inside"):
            release.main()


def test_settled_releases_tolerates_github_read_after_write_lag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[int] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    done = {"tag_name": TAG, "assets": [{"digest": f"sha256:{'0' * 64}"}]}
    reads = iter([[], [{"tag_name": TAG, "assets": []}], [done]])
    monkeypatch.setattr(release, "releases", lambda: next(reads))
    assert release.settled_releases(TAG, 1) == [done]
    assert sleeps == [0, 1, 2]

    sleeps.clear()
    monkeypatch.setattr(release, "releases", lambda: [])
    with pytest.raises(RuntimeError, match="did not settle"):
        release.settled_releases(TAG, 1)
    assert len(sleeps) == 6
