"""Release workflow safety tests using controlled GitHub API fakes."""

import json
import time
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
        if args[:4] == ("gh", "api", "--method", "POST"):
            assert args[4:] == (
                "repos/{owner}/{repo}/git/refs",
                "-f",
                f"ref=refs/tags/{tag}",
                "-f",
                f"sha={SHA}",
            )
            tags[tag] = SHA
            return "{}"
        assert args[:4] == ("gh", "release", "create", tag)
        assert "--verify-tag" in args and "--draft" in args
        assert ("--prerelease" in args) == (channel != "stable")
        assert args[args.index("--notes-file") + 1] == str(output / "release-notes.md")
        assets = [p for p in output.iterdir() if p.name != "release-notes.md"]
        assert all(str(asset) in args for asset in assets)
        records.append(
            {
                "tag_name": tag,
                "draft": True,
                "prerelease": channel != "stable",
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
    # Writes create one tag and one draft; publication is never attempted.
    assert len(calls) == 2
    assert "--draft" in calls[1]
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
    with pytest.raises(RuntimeError, match="Remote tags changed"):
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
    with pytest.raises(RuntimeError, match="Remote tags changed.*docs/development.md"):
        release.publish_draft(SHA, "alpha", output)
    assert not writes


def test_orphan_tag_and_other_draft_refuse_new_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "artifacts"
    artifacts(output, TAG, "alpha")
    orphan = {"v0.1.0": OTHER_SHA}
    monkeypatch.setattr(release, "validate_source", lambda _: None)
    monkeypatch.setattr(release, "local_tags", lambda: {})
    monkeypatch.setattr(release, "remote_tags", lambda: orphan)
    monkeypatch.setattr(release, "run", lambda *_: pytest.fail("unexpected write"))
    with pytest.raises(RuntimeError, match="Remote tags changed.*docs/development.md"):
        release.publish_draft(SHA, "alpha", output)

    prior_tags = {"v0.1.0": OTHER_SHA}
    artifacts(tmp_path / "with-draft", TAG, "alpha", prior_tags)
    monkeypatch.setattr(release, "local_tags", lambda: prior_tags)
    monkeypatch.setattr(release, "remote_tags", lambda: prior_tags)
    monkeypatch.setattr(
        release,
        "releases",
        lambda: [{"tag_name": "v0.1.0", "draft": True}],
    )
    with pytest.raises(RuntimeError, match="Other draft release.*docs/development.md"):
        release.publish_draft(SHA, "alpha", tmp_path / "with-draft")


def test_release_tag_inventory_must_match_releases() -> None:
    release.check_release_inventory([], [])
    with pytest.raises(RuntimeError, match="inventory differs.*docs/development.md"):
        release.check_release_inventory(["v0.1.0"], [])
    with pytest.raises(RuntimeError, match="inventory differs.*docs/development.md"):
        release.check_release_inventory([], [{"tag_name": "v0.1.0"}])


def record(
    tag: str = TAG,
    *,
    draft: bool = True,
    published_at: str | None = None,
    immutable: bool = False,
) -> dict[str, Any]:
    return {
        "id": 7,
        "tag_name": tag,
        "draft": draft,
        "published_at": published_at,
        "immutable": immutable,
    }


def test_recovery_refuses_published_ambiguous_old_or_mismatched_targets() -> None:
    tags = {TAG: SHA}
    assert release.recovery_target(TAG, SHA, tags, []) is None
    assert release.recovery_target(TAG, SHA, tags, [record()]) == 7
    for existing in (
        [record(draft=False)],
        [record(draft=True, published_at="2026-11-24")],
        [record(immutable=True)],
        [record(), record()],
    ):
        with pytest.raises(RuntimeError, match="published or ambiguous"):
            release.recovery_target(TAG, SHA, tags, existing)
    with pytest.raises(RuntimeError, match="explicitly supplied original SHA"):
        release.recovery_target(TAG, OTHER_SHA, tags, [record()])
    with pytest.raises(RuntimeError, match="newest"):
        release.recovery_target(TAG, SHA, {**tags, "v0.2.0": SHA}, [record()])


@pytest.mark.parametrize("has_draft", [True, False])
def test_recovery_requires_confirmation_and_uses_lease(
    monkeypatch: pytest.MonkeyPatch, has_draft: bool
) -> None:
    tags = {TAG: SHA}
    records = [record()] if has_draft else []
    calls: list[tuple[str, ...]] = []

    def gh(*args: str) -> str:
        calls.append(args)
        assert args == (
            "gh",
            "api",
            "--method",
            "DELETE",
            "repos/{owner}/{repo}/releases/7",
        )
        assert has_draft
        records.clear()
        return ""

    def git(*args: str) -> str:
        assert args == (
            "push",
            f"--force-with-lease=refs/tags/{TAG}:{SHA}",
            "origin",
            f":refs/tags/{TAG}",
        )
        assert not records
        tags.clear()
        return ""

    monkeypatch.setattr(release, "remote_tags", lambda: dict(tags))
    monkeypatch.setattr(release, "releases", lambda: list(records))
    monkeypatch.setattr(release, "run", gh)
    monkeypatch.setattr(release, "git", git)
    with pytest.raises(RuntimeError, match="confirmation"):
        release.recover(TAG, SHA, "wrong", "operator checked the history")
    assert not calls

    release.recover(TAG, SHA, f"NEVER PUBLISHED {TAG} {SHA}", "operator evidence")
    assert not tags
    assert not records
    assert len(calls) == int(has_draft)


def test_recovery_rechecks_before_any_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    tag_states = iter([{TAG: SHA}, {TAG: OTHER_SHA}])
    monkeypatch.setattr(release, "remote_tags", lambda: next(tag_states))
    monkeypatch.setattr(release, "releases", lambda: [record()])
    monkeypatch.setattr(
        release, "run", lambda *_: pytest.fail("unexpected release delete")
    )
    monkeypatch.setattr(release, "git", lambda *_: pytest.fail("unexpected tag delete"))
    with pytest.raises(RuntimeError, match="explicitly supplied original SHA"):
        release.recover(TAG, SHA, f"NEVER PUBLISHED {TAG} {SHA}", "operator evidence")


def test_workflow_contracts() -> None:
    root = Path(__file__).resolve().parents[2] / ".github/workflows"
    workflows = {path.name: path.read_text("utf-8") for path in root.glob("*.yml")}
    for name in ("development-build.yml", "release.yml", "recover-release.yml"):
        assert "workflow_dispatch" in workflows[name]
        assert "pull_request" not in workflows[name] and "push:" not in workflows[name]
    for name in ("release.yml", "recover-release.yml"):
        assert "muteinous-official-release" in workflows[name]
        assert "actions: read" not in workflows[name]
    assert "run_id" not in workflows["recover-release.yml"]
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
    for argv in (
        ["draft", "--sha", SHA, "--output", "x", "--channel", "alpha"],
        [
            "recover",
            "--tag",
            TAG,
            "--sha",
            SHA,
            "--confirmation",
            "confirmation",
            "--evidence",
            "evidence",
        ],
    ):
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
    assert release.settled_releases([TAG], TAG, 1) == [done]
    assert sleeps == [0, 1, 2]

    sleeps.clear()
    monkeypatch.setattr(release, "releases", lambda: [])
    with pytest.raises(RuntimeError, match="inventory differs"):
        release.settled_releases([TAG], TAG, 1)
    assert len(sleeps) == 6
