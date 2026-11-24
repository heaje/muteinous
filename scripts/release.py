"""Manual build/release orchestration; Commitizen owns version calculation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Pre-1.0 policy is deliberately not an input to workflow dispatch.
CHANNELS = {"alpha": "a", "beta": "b", "rc": "rc", "stable": None}
SHA = re.compile(r"[0-9a-f]{40}\Z")
BOOTSTRAP = "922b92ec08f6f711be2b5734000304459b13ba62"

if TYPE_CHECKING:
    from packaging.version import Version


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


def version_for_tag(tag: str) -> Version:
    from packaging.version import InvalidVersion, Version

    if not tag.startswith("v"):
        raise RuntimeError(f"Noncanonical release tag: {tag}")
    value = tag[1:]
    try:
        version = Version(value)
    except InvalidVersion as exc:
        raise RuntimeError(f"Noncanonical release tag: {tag}") from exc
    if (
        str(version) != value
        or version.epoch != 0
        or len(version.release) != 3
        or version.post is not None
        or version.dev is not None
        or version.local is not None
    ):
        raise RuntimeError(f"Noncanonical release tag: {tag}")
    return version


def validate_candidate(tag: str, channel: str, tags: list[str]) -> None:
    version = version_for_tag(tag)
    if version.release[0] != 0:
        raise RuntimeError(
            "1.0 (including prereleases) requires a reviewed policy/configuration change"
        )
    if (version.pre[0] if version.pre else None) != CHANNELS[channel]:
        raise RuntimeError(
            f"Commitizen proposed {tag}, not the requested {channel} channel"
        )
    if tag in tags:
        raise RuntimeError(
            f"Tag already exists: {tag}; never overwrite or silently reuse"
        )
    if tags and version <= max(map(version_for_tag, tags)):
        raise RuntimeError(f"Non-increasing release version: {tag}")


def validate_source(sha: str) -> None:
    if not SHA.fullmatch(sha) or git("rev-parse", "HEAD") != sha:
        raise RuntimeError("Checkout does not match the requested source SHA")
    if git("rev-parse", "--is-shallow-repository") != "false":
        raise RuntimeError("Full Git history and tags are required")
    if git("status", "--porcelain", "--untracked-files=normal"):
        raise RuntimeError("Source checkout is dirty")


def check_history() -> None:
    commits = git("rev-list", "HEAD").splitlines()
    if BOOTSTRAP not in commits:
        raise RuntimeError(
            "Release history does not include the Python bootstrap commit"
        )
    if BOOTSTRAP != git("rev-parse", "HEAD"):
        cz("check", "--rev-range", f"{BOOTSTRAP}..HEAD")


def local_tags() -> dict[str, str]:
    tags = git("tag", "--list").splitlines()
    return {tag: git("rev-parse", f"refs/tags/{tag}") for tag in tags}


def propose(channel: str) -> str:
    tags = local_tags()
    if tags:
        for tag in tags:
            version_for_tag(tag)
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
            "Git tag and published GitHub Release inventory differs; investigate before "
            "continuing"
        )


def refuse_drafts(existing: list[dict[str, Any]]) -> None:
    drafts = [str(item["tag_name"]) for item in existing if item["draft"]]
    if drafts:
        raise RuntimeError(
            "Draft release(s) already exist: "
            f"{', '.join(sorted(drafts))}. Delete or publish them before retrying"
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
    stable = [t for t in tags if version_for_tag(t).pre is None]
    # Commitizen otherwise labels same-SHA promotions with the previous tag.
    # Hide prerelease tags in this disposable checkout only, after calculating
    # the proposal from the complete tag history.
    for previous in tags:
        if version_for_tag(previous).pre is not None:
            git("tag", "-d", previous)
    args = ["changelog", "--dry-run", "--unreleased-version", tag]
    if stable:
        args += ["--start-rev", max(stable, key=version_for_tag)]
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
    channel: str | None = None,
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
        "channel": channel,
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
    build(
        sha,
        output,
        tag,
        source_tags=tags,
        release_notes=release_notes,
        channel=channel,
    )
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
    if (
        metadata["package"] != "muteinous"
        or metadata["sha"] != sha
        or metadata["version"] != tag[1:]
        or metadata["channel"] != channel
    ):
        raise RuntimeError("Artifact provenance does not match requested release")
    source_tags: dict[str, str] = metadata["source_tags"]
    if tag in source_tags:
        raise RuntimeError("Release tag already exists in its source tag inventory")
    (wheel,) = output.glob("*.whl")
    (sdist,) = output.glob("*.tar.gz")
    if (
        not wheel.name.startswith(f"muteinous-{tag[1:]}-")
        or sdist.name != f"muteinous-{tag[1:]}.tar.gz"
    ):
        raise RuntimeError("Distribution filenames do not match requested release")
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
    return tag, source_tags


def settled_releases(tag: str, asset_count: int) -> list[dict[str, Any]]:
    """Read releases after creation, tolerating GitHub's read-after-write lag.

    Only the read is retried, never the creation. Persistent disagreement still
    fails closed through draft validation.
    """
    for delay in (0, 1, 2, 4, 8, 15):
        time.sleep(delay)
        current = releases()
        match = [r for r in current if r["tag_name"] == tag]
        if len(match) == 1 and len(match[0]["assets"]) == asset_count:
            return current
    raise RuntimeError("Draft release or uploaded assets did not settle in GitHub")


def publish_draft(sha: str, channel: str, output: Path) -> None:
    validate_source(sha)
    tag, tags = validate_artifacts(output, sha, channel)
    if local_tags() != tags:
        raise RuntimeError("Local tags changed after preparation; start a fresh run")
    remote = remote_tags()
    if tag in remote:
        raise RuntimeError(
            f"Tag already exists remotely: {tag}; never reuse or move it"
        )
    if remote != tags:
        raise RuntimeError("Remote tags changed after preparation; start a fresh run")
    existing = releases()
    refuse_drafts(existing)
    check_release_inventory(list(tags), existing)
    remote = remote_tags()
    if remote != tags:
        raise RuntimeError("Remote tags changed during draft checks; start a fresh run")
    args = [
        "gh",
        "release",
        "create",
        tag,
        "--draft",
        "--target",
        sha,
        "--title",
        tag,
        "--notes-file",
        str(output / "release-notes.md"),
    ]
    if channel != "stable":
        args.append("--prerelease")
    args += [str(p) for p in sorted(output.iterdir()) if p.name != "release-notes.md"]
    print(run(*args), flush=True)
    count = sum(p.name != "release-notes.md" for p in output.iterdir())
    current_releases = settled_releases(tag, count)
    matches = [item for item in current_releases if item["tag_name"] == tag]
    if (
        len(matches) != 1
        or not matches[0]["draft"]
        or matches[0]["published_at"] is not None
        or matches[0].get("immutable")
        or matches[0]["prerelease"] != (channel != "stable")
        or matches[0].get("target_commitish") != sha
    ):
        raise RuntimeError(
            "Expected exactly one correctly classified draft targeting the validated SHA"
        )
    assets = {p.name: p for p in output.iterdir() if p.name != "release-notes.md"}
    uploaded = {asset["name"]: asset for asset in matches[0]["assets"]}
    if set(assets) != set(uploaded):
        raise RuntimeError("Draft asset inventory mismatch")
    for name, path in assets.items():
        asset = uploaded[name]
        if asset["state"] != "uploaded" or asset["size"] != path.stat().st_size:
            raise RuntimeError(f"Incomplete draft asset: {name}")
        if asset.get("digest") != f"sha256:{digest(path)}":
            raise RuntimeError(f"GitHub asset digest missing or mismatched: {name}")
    if remote_tags() != tags:
        raise RuntimeError("Draft creation unexpectedly changed remote tags")
    print(f"Draft {tag} created; review and publish manually.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("dev", "prepare", "draft"):
        p = sub.add_parser(command)
        p.add_argument("--sha", required=True)
        p.add_argument("--output", required=True, type=Path)
        if command != "dev":
            p.add_argument("--channel", choices=CHANNELS, required=True)
    args = parser.parse_args()
    if args.command == "draft" and os.getenv("GITHUB_ACTIONS") != "true":
        # Writes must come from the audited, concurrency-controlled workflows.
        raise SystemExit("draft may only run inside its GitHub workflow")
    if args.command == "dev":
        build(args.sha, args.output)
    elif args.command == "prepare":
        prepare(args.sha, args.channel, args.output)
    elif args.command == "draft":
        publish_draft(args.sha, args.channel, args.output)


if __name__ == "__main__":
    main()
