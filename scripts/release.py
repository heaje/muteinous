"""Manual build/release orchestration; Commitizen owns version calculation."""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# Pre-1.0 policy is deliberately not an input to workflow dispatch.
CHANNELS = {"alpha": "a", "beta": "b", "rc": "rc", "stable": None}
TAG = re.compile(
    r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:(a|b|rc)(0|[1-9]\d*))?\Z"
)
SHA = re.compile(r"[0-9a-f]{40}\Z")
# Exactly these pre-enforcement commits have nonconventional messages.
LEGACY = {
    "f1e4c747e316e80afb91b7cccdc1c3fbe60d6bef",
    "922b92ec08f6f711be2b5734000304459b13ba62",
}
BOOTSTRAP = "922b92ec08f6f711be2b5734000304459b13ba62"


def run(*args: str) -> str:
    result = subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    if result.returncode:
        raise RuntimeError(
            f"{args[0]} {args[1:]} failed ({result.returncode}): "
            f"{result.stderr.strip()} {result.stdout.strip()}"
        )
    return result.stdout.strip()


def git(*args: str) -> str:
    return run("git", *args)


def cz(*args: str) -> str:
    return run(sys.executable, "-m", "commitizen", *args)


def tag_key(tag: str) -> tuple[int, int, int, int, int]:
    match = TAG.fullmatch(tag)
    if not match:
        raise RuntimeError(f"Noncanonical release tag: {tag}")
    major, minor, patch, phase, number = match.groups()
    return (
        int(major),
        int(minor),
        int(patch),
        {"a": 0, "b": 1, "rc": 2, None: 3}[phase],
        int(number or 0),
    )


def validate_candidate(tag: str, channel: str, tags: list[str]) -> None:
    key = tag_key(tag)
    if key[0] != 0:
        raise RuntimeError(
            "D166: 1.0 (including prereleases) requires reviewed policy/configuration change"
        )
    match = TAG.fullmatch(tag)
    assert match is not None
    if match.group(4) != CHANNELS[channel]:
        raise RuntimeError(
            f"Commitizen proposed {tag}, not the requested {channel} channel"
        )
    if tag in tags:
        raise RuntimeError(
            f"Tag already exists: {tag}; never overwrite or silently reuse"
        )
    if tags and key <= max(map(tag_key, tags)):
        raise RuntimeError(f"Non-increasing release version: {tag}")


def validate_source(sha: str) -> None:
    if not SHA.fullmatch(sha) or git("rev-parse", "HEAD") != sha:
        raise RuntimeError("Checkout does not match the requested source SHA")
    if git("rev-parse", "--is-shallow-repository") != "false":
        raise RuntimeError("Full Git history and tags are required")
    if git("status", "--porcelain", "--untracked-files=normal"):
        raise RuntimeError("Source checkout is dirty")


def check_history() -> None:
    commits = set(git("rev-list", "HEAD").splitlines())
    if BOOTSTRAP in commits:
        # Check all later commits in one invocation; inspect the small bootstrap
        # history separately so the exceptions cannot exempt any future commits.
        before = git("rev-list", BOOTSTRAP).splitlines()
        if BOOTSTRAP != git("rev-parse", "HEAD"):
            cz("check", "--rev-range", f"{BOOTSTRAP}..HEAD")
        for commit in before:
            if commit not in LEGACY:
                cz("check", "--message", git("show", "-s", "--format=%B", commit))
    else:
        cz("check", "--rev-range", "HEAD")


def local_tags() -> dict[str, str]:
    tags = git("tag", "--list").splitlines()
    for tag in tags:
        tag_key(tag)
    return {tag: git("rev-parse", f"refs/tags/{tag}") for tag in tags}


def propose(channel: str) -> str:
    tags = local_tags()
    if tags:
        # All existing release tags must be reachable from the release source.
        # Refuse a divergent version history instead of guessing which line to bump.
        for tag in tags:
            git("merge-base", "--is-ancestor", tag, "HEAD")
    args = ["bump", "--get-next", "--yes"]
    if channel != "stable":
        args.extend(["--prerelease", channel, "--prerelease-offset", "1"])
    tag = "v" + cz(*args)
    validate_candidate(tag, channel, list(tags))
    return tag


def releases() -> list[dict[str, Any]]:
    # Explicit pagination includes drafts visible to the repository token.
    pages: list[list[dict[str, Any]]] = json.loads(
        run(
            "gh",
            "api",
            "--paginate",
            "--slurp",
            "repos/{owner}/{repo}/releases?per_page=100",
        )
    )
    return [release for page in pages for release in page]


def check_release_inventory(tags: list[str], existing: list[dict[str, Any]]) -> None:
    names = [str(item["tag_name"]) for item in existing]
    if len(names) != len(set(names)) or set(names) != set(tags):
        raise RuntimeError(
            "Remote release/tag inventory differs; investigate drafts, orphan tags, or deleted releases before continuing"
        )


def remote_tags() -> dict[str, str]:
    pages: list[list[dict[str, Any]]] = json.loads(
        run(
            "gh",
            "api",
            "--paginate",
            "--slurp",
            "repos/{owner}/{repo}/git/matching-refs/tags/?per_page=100",
        )
    )
    return {
        str(item["ref"]).removeprefix("refs/tags/"): str(item["object"]["sha"])
        for page in pages
        for item in page
    }


def notes(tag: str, tags: list[str]) -> str:
    # Cumulative notes since the last stable release, including prerelease
    # changes. Dry-run never writes a changelog file.
    stable = [t for t in tags if tag_key(t)[3] == 3]
    # Commitizen otherwise labels same-SHA promotions with the previous tag.
    # Hide prerelease tags in this disposable checkout only, after calculating
    # the proposal from the complete tag history.
    for previous in tags:
        if tag_key(previous)[3] != 3:
            git("tag", "-d", previous)
    args = ["changelog", "--dry-run", "--unreleased-version", tag]
    if stable:
        args += ["--start-rev", max(stable, key=tag_key)]
    result = cz(*args)
    if not result.strip():
        raise RuntimeError("Commitizen returned empty release notes")
    return result


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build(
    sha: str,
    output: Path,
    tag: str | None = None,
    *,
    source_tags: dict[str, str] | None = None,
    release_notes: str | None = None,
) -> None:
    validate_source(sha)
    if output.exists() or Path("dist").exists():
        raise RuntimeError(
            "Build requires fresh output directories (use a disposable checkout)"
        )
    if tag is not None and git("rev-parse", f"{tag}^{{commit}}") != sha:
        raise RuntimeError("Release tag does not resolve to the build source")
    version = run(sys.executable, "-m", "setuptools_scm")
    if tag is not None and version != tag[1:]:
        raise RuntimeError(f"SCM version {version} does not match {tag}")
    # The existing locked build helper checks both metadata versions and
    # installs/imports the wheel in an isolated environment.
    print(run(sys.executable, "scripts/check_package.py"), flush=True)
    (wheel,) = Path("dist").glob("*.whl")
    (sdist,) = Path("dist").glob("*.tar.gz")
    output.mkdir(parents=True)
    for path in (wheel, sdist):
        shutil.move(path, output / path.name)
    metadata: dict[str, Any] = {
        "package": "muteinous",
        "version": version,
        "tag": tag,
        "sha": sha,
        "python": sys.version,
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "runner_os": os.getenv("RUNNER_OS"),
            "runner_arch": os.getenv("RUNNER_ARCH"),
            "image_os": os.getenv("ImageOS"),
            "image_version": os.getenv("ImageVersion"),
            "uv": run("uv", "--version"),
            "lock_sha256": digest(Path("uv.lock")),
            "run_url": (
                f"{os.getenv('GITHUB_SERVER_URL')}/{os.getenv('GITHUB_REPOSITORY')}"
                f"/actions/runs/{os.getenv('GITHUB_RUN_ID')}"
            ),
            "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
        },
        "artifacts": {p.name: digest(output / p.name) for p in (wheel, sdist)},
    }
    if tag is not None:
        if source_tags is None or release_notes is None:
            raise RuntimeError("Release build requires version history and notes")
        notes_path = output / "release-notes.md"
        notes_path.write_text(release_notes + "\n", encoding="utf-8", newline="\n")
        metadata["source_tags"] = source_tags
        metadata["notes_sha256"] = digest(notes_path)
    (output / "build-metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    write_checksums(output)
    print(json.dumps(metadata, indent=2), flush=True)


def write_checksums(output: Path) -> None:
    files = sorted(
        p for p in output.iterdir() if p.name not in {"SHA256SUMS", "release-notes.md"}
    )
    (output / "SHA256SUMS").write_text(
        "".join(f"{digest(p)}  {p.name}\n" for p in files),
        encoding="utf-8",
        newline="\n",
    )


def prepare(sha: str, channel: str, output: Path, *, remote: bool = True) -> None:
    validate_source(sha)
    check_history()
    tags = local_tags()
    if remote and remote_tags() != tags:
        raise RuntimeError("Remote tags changed; start a fresh release run")
    tag = propose(channel)
    release_notes = notes(tag, list(tags))
    # A new tag can share a commit with previous prereleases. Git describe
    # otherwise chooses an arbitrary exact-match tag. Only in this disposable
    # local checkout, remove other exact-match tags; remote tags are untouched.
    for old in git("tag", "--points-at", sha).splitlines():
        git("tag", "-d", old)
    git("tag", tag, sha)
    git("checkout", "--detach", tag)
    build(sha, output, tag, source_tags=tags, release_notes=release_notes)
    print(
        f"Prepared {tag} from {sha}; no remote tag or release created yet", flush=True
    )


def validate_artifacts(
    output: Path, sha: str, channel: str
) -> tuple[str, dict[str, str]]:
    metadata: dict[str, Any] = json.loads(
        (output / "build-metadata.json").read_text(encoding="utf-8")
    )
    tag = str(metadata["tag"])
    validate_candidate(tag, channel, [])
    if metadata["sha"] != sha or metadata["version"] != tag[1:]:
        raise RuntimeError("Artifact provenance does not match requested release")
    (wheel,) = output.glob("*.whl")
    (sdist,) = output.glob("*.tar.gz")
    assets = {wheel.name, sdist.name, "build-metadata.json"}
    expected = assets | {"release-notes.md", "SHA256SUMS"}
    if {p.name for p in output.iterdir()} != expected:
        raise RuntimeError("Unexpected or missing release artifact")
    if metadata["artifacts"] != {p.name: digest(p) for p in (wheel, sdist)}:
        raise RuntimeError("Distribution checksum mismatch")
    if metadata["notes_sha256"] != digest(output / "release-notes.md"):
        raise RuntimeError("Generated release notes checksum mismatch")
    sums = "".join(f"{digest(output / name)}  {name}\n" for name in sorted(assets))
    if (output / "SHA256SUMS").read_text(encoding="utf-8") != sums:
        raise RuntimeError("Release checksum manifest mismatch")
    source_tags: dict[str, str] = metadata["source_tags"]
    validate_candidate(tag, channel, list(source_tags))
    return tag, source_tags


def publish_draft(sha: str, channel: str, output: Path) -> None:
    validate_source(sha)
    tag, tags = validate_artifacts(output, sha, channel)
    if remote_tags() != tags or local_tags() != tags:
        raise RuntimeError("Remote tags changed after build; start a fresh release run")
    # Only the write-enabled job can reliably enumerate private draft releases.
    check_release_inventory(list(tags), releases())
    # Atomic creation; GitHub refuses a pre-existing ref. No force/update.
    print(
        f"Creating {tag} at {sha}; if a later operation fails use documented recovery",
        flush=True,
    )
    run(
        "gh",
        "api",
        "--method",
        "POST",
        "repos/{owner}/{repo}/git/refs",
        "-f",
        f"ref=refs/tags/{tag}",
        "-f",
        f"sha={sha}",
    )
    args = [
        "gh",
        "release",
        "create",
        tag,
        "--verify-tag",
        "--draft",
        "--title",
        tag,
        "--notes-file",
        str(output / "release-notes.md"),
    ]
    if channel != "stable":
        args.append("--prerelease")
    args += [str(p) for p in sorted(output.iterdir()) if p.name != "release-notes.md"]
    print(run(*args), flush=True)
    matches = [item for item in releases() if item["tag_name"] == tag]
    if (
        len(matches) != 1
        or not matches[0]["draft"]
        or matches[0]["published_at"] is not None
        or matches[0]["prerelease"] != (channel != "stable")
    ):
        raise RuntimeError(
            "Expected exactly one correctly classified draft; inspect before publishing"
        )
    assets = {p.name: p for p in output.iterdir() if p.name != "release-notes.md"}
    uploaded = {asset["name"]: asset for asset in matches[0]["assets"]}
    if set(assets) != set(uploaded):
        raise RuntimeError("Draft asset inventory mismatch")
    for name, path in assets.items():
        asset = uploaded[name]
        if asset["state"] != "uploaded" or asset["size"] != path.stat().st_size:
            raise RuntimeError(f"Incomplete draft asset: {name}")
        if asset.get("digest") and asset["digest"] != f"sha256:{digest(path)}":
            raise RuntimeError(f"GitHub asset digest mismatch: {name}")
    if remote_tags().get(tag) != sha:
        raise RuntimeError("Remote tag no longer matches validated source")
    print(f"Draft {tag} created; review and publish manually.", flush=True)


def recovery_target(
    tag: str, sha: str, tags: dict[str, str], existing: list[dict[str, Any]]
) -> int | None:
    tag_key(tag)
    if not SHA.fullmatch(sha) or tags.get(tag) != sha:
        raise RuntimeError(
            "Tag is missing or does not match the explicitly supplied original SHA"
        )
    if tag != max(tags, key=tag_key):
        raise RuntimeError("Only the newest failed release can be reset")
    matches = [item for item in existing if item["tag_name"] == tag]
    check_release_inventory(
        [previous for previous in tags if previous != tag],
        [item for item in existing if item["tag_name"] != tag],
    )
    if not matches:
        # Orphan tag: requires independent operator evidence/attestation.
        return None
    if (
        len(matches) != 1
        or not matches[0]["draft"]
        or matches[0]["published_at"] is not None
    ):
        raise RuntimeError("Refusing to reset a published or ambiguous release")
    return int(matches[0]["id"])


def recover(tag: str, sha: str, confirmation: str, run_id: str, evidence: str) -> None:
    if (
        confirmation != f"NEVER PUBLISHED {tag} {sha}"
        or not evidence.strip()
        or not re.fullmatch(r"[0-9]+", run_id)
    ):
        raise RuntimeError(
            "Supply exact never-published confirmation, original run ID and failure evidence"
        )
    original: dict[str, Any] = json.loads(
        run("gh", "api", f"repos/{{owner}}/{{repo}}/actions/runs/{run_id}")
    )
    if (
        original["head_sha"] != sha
        or original["event"] != "workflow_dispatch"
        or original["path"].split("@", 1)[0] != ".github/workflows/release.yml"
        or original["status"] != "completed"
    ):
        raise RuntimeError(
            "Original run is not a completed official release for this SHA"
        )
    print(
        f"Recovery requested: {tag} {sha}; original run: {run_id}; evidence: {evidence!r}",
        flush=True,
    )
    release_id = recovery_target(tag, sha, remote_tags(), releases())
    if release_id is None and original["conclusion"] == "success":
        raise RuntimeError("Orphan reset requires an unsuccessful original release run")
    if release_id is not None:
        # Recheck immediately before deleting; never use --cleanup-tag.
        item: dict[str, Any] = json.loads(
            run("gh", "api", f"repos/{{owner}}/{{repo}}/releases/{release_id}")
        )
        if (
            item["tag_name"] != tag
            or not item["draft"]
            or item["published_at"] is not None
        ):
            raise RuntimeError("Draft changed; refusing recovery")
        run(
            "gh",
            "api",
            "--method",
            "DELETE",
            f"repos/{{owner}}/{{repo}}/releases/{release_id}",
        )
    if any(item["tag_name"] == tag for item in releases()):
        raise RuntimeError("Release still exists; refusing tag deletion")
    # Lease protects against deleting a tag moved since confirmation.
    ref = f"refs/tags/{tag}"
    git("push", f"--force-with-lease={ref}:{sha}", "origin", f":{ref}")
    if tag in remote_tags():
        raise RuntimeError("Tag still exists after deletion")
    print(
        "Reset complete. Fix through PR, then dispatch a fresh release. "
        "Previously fetched tags may remain.",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("dev", "prepare", "draft"):
        p = sub.add_parser(command)
        p.add_argument("--sha", required=True)
        p.add_argument("--output", required=True, type=Path)
        if command != "dev":
            p.add_argument("--channel", choices=CHANNELS, required=True)
    p = sub.add_parser("recover")
    p.add_argument("--tag", required=True)
    p.add_argument("--sha", required=True)
    p.add_argument("--confirmation", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--evidence", required=True)
    args = parser.parse_args()
    if args.command == "dev":
        build(args.sha, args.output)
    elif args.command == "prepare":
        prepare(args.sha, args.channel, args.output)
    elif args.command == "draft":
        publish_draft(args.sha, args.channel, args.output)
    else:
        recover(args.tag, args.sha, args.confirmation, args.run_id, args.evidence)


if __name__ == "__main__":
    main()
