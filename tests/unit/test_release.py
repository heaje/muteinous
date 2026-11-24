"""Deterministic release orchestration and failure-path tests."""

import json
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
        ("v0.2.0a1", "alpha", ["v0.2.0a1"], "already exists"),
        ("v0.2.0a1", "alpha", ["v0.2.0b1"], "Non-increasing"),
        ("v0.2.0b1", "alpha", [], "not the requested"),
        ("v0.02.0", "stable", [], "Noncanonical"),
        ("v0.1١.0", "stable", [], "Noncanonical"),
        ("v0.2.0.dev1", "stable", [], "Noncanonical"),
    ],
)
def test_candidate_guards(
    tag: str, channel: str, existing: list[str], message: str
) -> None:
    with pytest.raises(RuntimeError, match=message):
        release.validate_candidate(tag, channel, existing)


def artifacts(output: Path, tag: str) -> None:
    # Synthetic files exercise the transfer protocol, not package validity.
    # Actual package builds for all four channels are tested in test_versioning.
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
        "source_tags": {},
        "environment": {
            **release.workflow_provenance(),
            "lock_sha256": release.digest(Path("uv.lock")),
        },
        "notes_sha256": release.digest(notes),
        "artifacts": {p.name: release.digest(p) for p in (wheel, sdist)},
    }
    (output / "build-metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
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
def test_only_draft_is_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, channel: str, tag: str
) -> None:
    output = tmp_path / "artifacts"
    artifacts(output, tag)
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
        assert "--verify-tag" in args
        assert "--draft" in args
        assert ("--prerelease" in args) == (channel != "stable")
        assert args[args.index("--notes-file") + 1] == str(output / "release-notes.md")
        assets = [p for p in output.iterdir() if p.name != "release-notes.md"]
        for asset in assets:
            assert str(asset) in args
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
                        "digest": f"sha256:{release.digest(p)}",
                    }
                    for p in assets
                ],
            }
        )
        return "draft URL"

    monkeypatch.setattr(release, "validate_source", lambda _: None)
    monkeypatch.setattr(release, "remote_tags", lambda: dict(tags))
    monkeypatch.setattr(release, "local_tags", dict)
    monkeypatch.setattr(release, "releases", lambda: list(records))
    monkeypatch.setattr(release, "run", gh)
    release.publish_draft(SHA, channel, output)
    assert len(calls) == 2
    release.check_existing_drafts(records)
    # The only writes are a new tag and a draft. No publication/edit operation.
    assert records[0]["draft"] is True


@pytest.mark.parametrize(
    ("file", "message"),
    [
        ("muteinous-0.2.0a1-py3-none-any.whl", "Distribution checksum"),
        ("release-notes.md", "notes checksum"),
        ("SHA256SUMS", "manifest mismatch"),
    ],
)
def test_artifact_tampering_is_rejected(
    tmp_path: Path, file: str, message: str
) -> None:
    output = tmp_path / "artifacts"
    artifacts(output, TAG)
    (output / file).write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match=message):
        release.validate_artifacts(output, SHA, "alpha")


def test_new_remote_tag_prevents_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "artifacts"
    artifacts(output, TAG)
    monkeypatch.setattr(release, "validate_source", lambda _: None)
    monkeypatch.setattr(release, "remote_tags", lambda: {TAG: SHA})
    monkeypatch.setattr(release, "run", lambda *_: pytest.fail("unexpected write"))
    with pytest.raises(RuntimeError, match="Remote tags changed"):
        release.publish_draft(SHA, "alpha", output)


def test_release_inventory_refuses_orphans_and_missing_tags() -> None:
    release.check_release_inventory([TAG], [{"tag_name": TAG}])
    with pytest.raises(RuntimeError, match="inventory differs"):
        release.check_release_inventory([TAG], [])
    with pytest.raises(RuntimeError, match="inventory differs"):
        release.check_release_inventory([], [{"tag_name": TAG}])


def record(*, draft: bool = True, published_at: str | None = None) -> dict[str, Any]:
    return {
        "id": 7,
        "tag_name": TAG,
        "draft": draft,
        "published_at": published_at,
    }


def test_recovery_refuses_published_mismatched_or_nonlatest_tags() -> None:
    assert release.recovery_target(TAG, SHA, {TAG: SHA}, [record()]) == 7
    assert release.recovery_target(TAG, SHA, {TAG: SHA}, []) is None
    for item in (
        record(draft=False, published_at="2026-11-24"),
        record(draft=True, published_at="2026-11-24"),
    ):
        with pytest.raises(RuntimeError, match="published"):
            release.recovery_target(TAG, SHA, {TAG: SHA}, [item])
    with pytest.raises(RuntimeError, match="explicitly supplied original SHA"):
        release.recovery_target(TAG, OTHER_SHA, {TAG: SHA}, [record()])
    with pytest.raises(RuntimeError, match="newest"):
        release.recovery_target(TAG, SHA, {TAG: SHA, "v0.2.0": SHA}, [record()])


@pytest.mark.parametrize("has_draft", [True, False])
def test_recovery_requires_evidence_and_lease(
    monkeypatch: pytest.MonkeyPatch, has_draft: bool
) -> None:
    tags = {TAG: SHA}
    records = [record()] if has_draft else []
    calls: list[tuple[str, ...]] = []

    def gh(*args: str) -> str:
        calls.append(args)
        if args[-1].endswith("/actions/runs/42"):
            return json.dumps(
                {
                    "head_sha": SHA,
                    "event": "workflow_dispatch",
                    "path": ".github/workflows/release.yml",
                    "status": "completed",
                    "conclusion": "failure",
                }
            )
        if "/jobs?" in args[-1]:
            return json.dumps(
                [
                    {
                        "jobs": [
                            {
                                "name": "Create immutable-source tag and draft release",
                                "id": 123,
                            }
                        ]
                    }
                ]
            )
        if args[-1].endswith("/actions/jobs/123/logs"):
            return f"2026-11-24T00:00:00Z CREATED RELEASE TAG {TAG} {SHA}"
        assert has_draft
        assert args[-1].endswith("/releases/7")
        if "--method" not in args:
            return json.dumps(records[0])
        assert args[2:4] == ("--method", "DELETE")
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
        release.recover(TAG, SHA, "yes", "42", "failed upload")
    assert not calls
    release.recover(TAG, SHA, f"NEVER PUBLISHED {TAG} {SHA}", "42", "failed upload")
    assert not tags
    assert not records


def test_reject_previous_incomplete_draft() -> None:
    item = {
        **record(),
        "prerelease": True,
        "assets": [],
    }
    with pytest.raises(RuntimeError, match="Incomplete or ambiguous existing draft"):
        release.check_existing_drafts([item])


def test_reject_stale_run_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/disposable")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    output = tmp_path / "artifacts"
    artifacts(output, TAG)
    release.validate_run_provenance(output)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    with pytest.raises(RuntimeError, match="different run or attempt"):
        release.validate_run_provenance(output)
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setattr(release, "digest", lambda _: "different lock hash")
    with pytest.raises(RuntimeError, match="dependency lock differs"):
        release.validate_run_provenance(output)


def test_recovery_requires_exact_tag_creation_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log = f"2026-11-24T00:00:00Z CREATED RELEASE TAG {TAG} {SHA}"

    def gh(*args: str) -> str:
        if "/jobs?" in args[-1]:
            return json.dumps(
                [
                    {
                        "jobs": [
                            {
                                "name": "Create immutable-source tag and draft release",
                                "id": 123,
                            }
                        ]
                    }
                ]
            )
        assert args[-1].endswith("/actions/jobs/123/logs")
        return log

    monkeypatch.setattr(release, "run", gh)
    release.verify_creation_log("42", TAG, SHA)
    with pytest.raises(RuntimeError, match="did not prove creation"):
        release.verify_creation_log("42", "v0.2.0b1", SHA)
    with pytest.raises(RuntimeError, match="did not prove creation"):
        release.verify_creation_log("42", TAG, OTHER_SHA)
