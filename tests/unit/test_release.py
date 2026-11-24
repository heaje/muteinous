"""Deterministic release orchestration and failure-path tests."""

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
        ("v0.2.0a1", "alpha", ["v0.2.0a1"], "already exists"),
        ("v0.2.0a1", "alpha", ["v0.2.0b1"], "Non-increasing"),
        ("v0.2.0b1", "alpha", [], "not the requested"),
        ("v0.02.0", "stable", [], "Noncanonical"),
        ("v0.1Ãƒâ„¢Ã‚Â¡.0", "stable", [], "Noncanonical"),
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
    monkeypatch.setattr(release, "remote_tags", lambda: dict(tags))
    monkeypatch.setattr(release, "local_tags", dict)
    monkeypatch.setattr(release, "releases", lambda: list(records))
    monkeypatch.setattr(release, "run", gh)
    if digest_state == "valid":
        release.publish_draft(SHA, channel, output)
        release.check_existing_drafts(records)
    else:
        with pytest.raises(RuntimeError, match="digest missing or mismatched"):
            release.publish_draft(SHA, channel, output)
        with pytest.raises(RuntimeError, match="(?i)existing draft"):
            release.check_existing_drafts(records)
    # The only writes are a new tag and a draft. No publication/edit operation.
    assert len(calls) == 2


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


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out"])
@pytest.mark.parametrize("has_draft", [True, False])
def test_recovery_requires_evidence_and_lease(
    monkeypatch: pytest.MonkeyPatch, has_draft: bool, conclusion: str
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
                    "conclusion": conclusion,
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


def test_recovery_refuses_tag_moved_before_draft_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tags = iter([{TAG: SHA}, {TAG: OTHER_SHA}])

    def gh(*args: str) -> str:
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
        pytest.fail("Unexpected release deletion or API call")

    monkeypatch.setattr(release, "run", gh)
    monkeypatch.setattr(release, "verify_creation_log", lambda *_: None)
    monkeypatch.setattr(release, "remote_tags", lambda: next(tags))
    monkeypatch.setattr(release, "releases", lambda: [record()])
    monkeypatch.setattr(release, "git", lambda *_: pytest.fail("Unexpected tag write"))
    with pytest.raises(RuntimeError, match="explicitly supplied original SHA"):
        release.recover(TAG, SHA, f"NEVER PUBLISHED {TAG} {SHA}", "42", "failed upload")


@pytest.mark.parametrize("conclusion", ["success", "failure", "cancelled"])
def test_existing_draft_requires_successful_original_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, conclusion: str
) -> None:
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/disposable")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    output = tmp_path / "artifacts"
    artifacts(output, TAG)
    metadata = output / "build-metadata.json"
    item = {
        **record(),
        "assets": [
            {
                "id": 12,
                "name": metadata.name,
                "digest": f"sha256:{release.digest(metadata)}",
            },
            *(
                {"id": 13, "name": p.name, "digest": f"sha256:{release.digest(p)}"}
                for p in output.glob("muteinous-*")
            ),
        ],
    }

    def gh(*args: str) -> str:
        if args[-1].endswith("/releases/assets/12"):
            return metadata.read_text("utf-8").strip()
        assert args[-1].endswith("/actions/runs/42/attempts/2")
        return json.dumps(
            {
                "head_sha": SHA,
                "event": "workflow_dispatch",
                "path": ".github/workflows/release.yml",
                "status": "completed",
                "conclusion": conclusion,
            }
        )

    monkeypatch.setattr(release, "run", gh)
    if conclusion == "success":
        release.verify_prior_draft_run(item, SHA)
    else:
        with pytest.raises(RuntimeError, match="no successful original release run"):
            release.verify_prior_draft_run(item, SHA)


def test_existing_draft_distribution_must_match_recorded_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A swapped wheel with a regenerated manifest is not the built artifact."""
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/disposable")
    output = tmp_path / "artifacts"
    artifacts(output, TAG)
    metadata = output / "build-metadata.json"
    item = {
        **record(),
        "assets": [
            {
                "id": 12,
                "name": metadata.name,
                "digest": f"sha256:{release.digest(metadata)}",
            },
            {
                "id": 13,
                "name": "muteinous-0.2.0a1.tar.gz",
                "digest": f"sha256:{'0' * 64}",
            },
            {
                "id": 14,
                "name": "muteinous-0.2.0a1-py3-none-any.whl",
                "digest": f"sha256:{'1' * 64}",
            },
        ],
    }
    monkeypatch.setattr(release, "run", lambda *_: metadata.read_text("utf-8").strip())
    with pytest.raises(RuntimeError, match="differ from build"):
        release.verify_prior_draft_run(item, SHA)


@pytest.mark.parametrize(
    "conclusion", ["success", "neutral", "skipped", "action_required"]
)
@pytest.mark.parametrize("has_draft", [True, False])
def test_recovery_refuses_non_failed_original_run(
    monkeypatch: pytest.MonkeyPatch, conclusion: str, has_draft: bool
) -> None:
    def gh(*args: str) -> str:
        assert args[-1].endswith("/actions/runs/42"), "no write may be attempted"
        return json.dumps(
            {
                "head_sha": SHA,
                "event": "workflow_dispatch",
                "path": ".github/workflows/release.yml",
                "status": "completed",
                "conclusion": conclusion,
            }
        )

    monkeypatch.setattr(release, "run", gh)
    monkeypatch.setattr(release, "verify_creation_log", lambda *_: None)
    monkeypatch.setattr(release, "remote_tags", lambda: {TAG: SHA})
    monkeypatch.setattr(release, "releases", lambda: [record()] if has_draft else [])
    monkeypatch.setattr(release, "git", lambda *_: pytest.fail("Unexpected tag write"))
    with pytest.raises(RuntimeError, match="failed, cancelled or timed-out"):
        release.recover(TAG, SHA, f"NEVER PUBLISHED {TAG} {SHA}", "42", "evidence")


def test_creation_marker_may_come_from_an_earlier_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs = [
        {"name": "Create immutable-source tag and draft release", "id": i}
        for i in (1, 2)
    ]
    logs = {"1": f"2026-11-24T00:00:00Z CREATED RELEASE TAG {TAG} {SHA}", "2": "rerun"}

    def gh(*args: str) -> str:
        if "/jobs?" in args[-1]:
            assert "filter=all" in args[-1]
            return json.dumps([{"jobs": jobs}])
        return logs[args[-1].split("/")[-2]]

    monkeypatch.setattr(release, "run", gh)
    release.verify_creation_log("42", TAG, SHA)
    logs["1"] = "rerun"
    with pytest.raises(RuntimeError, match="did not prove creation"):
        release.verify_creation_log("42", TAG, SHA)


def test_remote_inventory_adapters_parse_slurped_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = {
        "releases": [[{"tag_name": TAG}], [{"tag_name": "v0.2.0b1"}]],
        "matching-refs": [
            [{"ref": f"refs/tags/{TAG}", "object": {"sha": SHA}}],
            [{"ref": "refs/tags/v0.2.0b1", "object": {"sha": OTHER_SHA}}],
        ],
    }

    def gh(*args: str) -> str:
        assert args[:4] == ("gh", "api", "--paginate", "--slurp")
        return json.dumps(
            pages["releases" if "/releases?" in args[-1] else "matching-refs"]
        )

    monkeypatch.setattr(release, "run", gh)
    assert [r["tag_name"] for r in release.releases()] == [TAG, "v0.2.0b1"]
    assert release.remote_tags() == {TAG: SHA, "v0.2.0b1": OTHER_SHA}


def test_workflow_contracts() -> None:
    """Cheap structural guards; live dispatch is separate acceptance evidence."""
    root = Path(__file__).resolve().parents[2] / ".github/workflows"
    text = {p.name: p.read_text("utf-8") for p in root.glob("*.yml")}
    for name in ("development-build.yml", "release.yml", "recover-release.yml"):
        assert "workflow_dispatch" in text[name]
        assert "pull_request" not in text[name] and "push:" not in text[name]
    for name in ("development-build.yml", "release.yml"):
        assert "retention-days" not in text[name]
    assert "--draft" in (root.parent.parent / "scripts/release.py").read_text("utf-8")
    assert (
        "twine" not in "".join(text.values())
        and "pypi" not in "".join(text.values()).lower()
    )
    assert "timeout-minutes: 10" in text["pr.yml"]
    assert text["release.yml"].count("muteinous-official-release") == 1
    assert text["recover-release.yml"].count("muteinous-official-release") == 1
    assert "gh release edit" not in "".join(text.values())
    assert "--cleanup-tag" not in "".join(text.values())


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
            "c",
            "--run-id",
            "1",
            "--evidence",
            "e",
        ],
    ):
        monkeypatch.setattr("sys.argv", ["release.py", *argv])
        with pytest.raises(SystemExit, match="only run inside"):
            release.main()


def test_settled_releases_tolerates_lag_but_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[int] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    done = {"tag_name": TAG, "assets": [{"digest": "sha256:" + "0" * 64}]}
    reads = iter([[], [{"tag_name": TAG, "assets": []}], [done]])
    monkeypatch.setattr(release, "releases", lambda: next(reads))
    assert release.settled_releases([TAG], TAG, 1) == [done]
    assert sleeps == [0, 1, 2]
    # A release that never appears is refused after the bounded wait.
    sleeps.clear()
    monkeypatch.setattr(release, "releases", lambda: [])
    with pytest.raises(RuntimeError, match="inventory differs"):
        release.settled_releases([TAG], TAG, 1)
    assert len(sleeps) == 6
