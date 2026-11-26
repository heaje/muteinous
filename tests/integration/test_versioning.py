"""Verify our release tooling against representative real provider boundaries."""

import json
import shutil
import subprocess
import sys
import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest
from packaging.requirements import Requirement

from scripts import release


def run(root: Path, *args: str) -> str:
    return subprocess.run(
        args, cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def use_synthetic_package_build(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace only packaging; keep real Git, SCM, release logic and hashing."""
    real_run = release.run
    scm_version: str | None = None

    def run_with_synthetic_build(*args: str) -> str:
        nonlocal scm_version
        if args == (sys.executable, "scripts/check_package.py"):
            assert scm_version is not None
            dist = Path("dist")
            dist.mkdir()
            (dist / f"muteinous-{scm_version}-py3-none-any.whl").write_bytes(
                b"synthetic wheel"
            )
            (dist / f"muteinous-{scm_version}.tar.gz").write_bytes(
                b"synthetic source distribution"
            )
            return "synthetic package build"
        result = real_run(*args)
        if args == (sys.executable, "-m", "setuptools_scm"):
            scm_version = result
        return result

    monkeypatch.setattr(release, "run", run_with_synthetic_build)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo with spaces"
    repo.mkdir()
    source = Path(__file__).resolve().parents[2]
    shutil.copy2(source / "pyproject.toml", repo)
    shutil.copy2(source / ".gitignore", repo)
    shutil.copy2(source / "uv.lock", repo)
    (repo / "scripts").mkdir()
    shutil.copy2(source / "scripts/check_package.py", repo / "scripts")
    shutil.copytree(
        source / "src",
        repo / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"),
    )
    run(repo, "git", "init", "--template=")
    hooks = tmp_path / "empty-hooks"
    hooks.mkdir()
    run(repo, "git", "config", "core.hooksPath", str(hooks))
    run(repo, "git", "config", "tag.gpgsign", "false")
    run(repo, "git", "config", "user.name", "Version Test")
    run(repo, "git", "config", "user.email", "test@example.invalid")
    run(repo, "git", "config", "commit.gpgsign", "false")
    run(repo, "git", "add", ".")
    run(repo, "git", "commit", "-m", "feat: initial package")
    return repo


@pytest.mark.portable
def test_configured_pre_one_breaking_bump(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo)
    run(repo, "git", "tag", "v0.2.0")
    run(repo, "git", "commit", "--allow-empty", "-m", "feat!: change interface")
    assert release.propose("stable") == "v0.3.0"
    assert set(release.local_tags()) == {"v0.2.0"}


@pytest.mark.portable
def test_version_preview_no_increment_and_nonmutation(repo: Path) -> None:
    run(repo, "git", "tag", "v0.2.0")
    run(repo, "git", "commit", "--allow-empty", "-m", "docs: clarify usage")
    before = run(repo, "git", "rev-parse", "HEAD")
    cz = [sys.executable, "-m", "commitizen"]
    args = ["bump", "--get-next", "--yes"]
    run(repo, *cz, "--no-raise", "NO_INCREMENT,NO_COMMITS_FOUND", *args)
    assert run(repo, "git", "status", "--porcelain") == ""
    assert run(repo, "git", "rev-parse", "HEAD") == before
    assert run(repo, "git", "tag", "--list") == "v0.2.0"


@pytest.mark.portable
def test_version_preview_at_stable_tag_and_nonmutation(repo: Path) -> None:
    run(repo, "git", "tag", "v0.2.0")
    before = (
        run(repo, "git", "rev-parse", "HEAD"),
        run(repo, "git", "tag", "--list"),
        run(repo, "git", "status", "--porcelain"),
    )
    cz = [sys.executable, "-m", "commitizen"]
    args = ["bump", "--get-next", "--yes"]

    run(repo, *cz, "--no-raise", "NO_INCREMENT,NO_COMMITS_FOUND", *args)

    assert run(repo, "git", "rev-parse", "HEAD") == before[0]
    assert run(repo, "git", "tag", "--list") == before[1] == "v0.2.0"
    assert run(repo, "git", "rev-parse", "v0.2.0") == before[0]
    assert run(repo, "git", "status", "--porcelain") == before[2] == ""


@pytest.mark.portable
def test_version_preview_propagates_other_failures(tmp_path: Path) -> None:
    outside = tmp_path / "not-a-git-repo"
    outside.mkdir()
    root = Path(__file__).resolve().parents[2]
    shutil.copy2(root / "pyproject.toml", outside)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "commitizen",
            "--no-raise",
            "NO_INCREMENT,NO_COMMITS_FOUND",
            "bump",
            "--get-next",
            "--yes",
        ],
        cwd=outside,
    )
    assert result.returncode != 0


@pytest.mark.portable
def test_release_source_and_history_validation(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo)
    sha = run(repo, "git", "rev-parse", "HEAD")
    monkeypatch.setattr(release, "BOOTSTRAP", sha)
    release.validate_source(sha)
    release.check_history()
    with pytest.raises(RuntimeError, match="requested source SHA"):
        release.validate_source("0" * 40)
    dirty = repo / "untracked.txt"
    dirty.write_text("not a clean release", encoding="utf-8")
    with pytest.raises(RuntimeError, match="dirty"):
        release.validate_source(sha)
    dirty.unlink()
    run(repo, "git", "commit", "--allow-empty", "-m", "not conventional")
    with pytest.raises(RuntimeError, match="commitizen"):
        release.check_history()


@pytest.mark.portable
def test_release_divergent_tag_is_rejected(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo)
    original = run(repo, "git", "rev-parse", "HEAD")
    run(repo, "git", "commit", "--allow-empty", "-m", "feat: another revision")
    run(repo, "git", "tag", "v0.1.0")
    run(repo, "git", "checkout", "--detach", original)
    with pytest.raises(RuntimeError, match="merge-base"):
        release.propose("stable")


@pytest.mark.portable
def test_prepare_release_from_own_tag(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Exercise the real release orchestration and providers once, with
    # previous prerelease tags on the same SHA. The packaging subprocess is
    # covered separately by the real tagged package smoke test.
    use_synthetic_package_build(monkeypatch)
    sha = run(repo, "git", "rev-parse", "HEAD")
    monkeypatch.setattr(release, "BOOTSTRAP", sha)
    tag = "v0.1.0rc1"
    previous = dict.fromkeys(("v0.1.0a1", "v0.1.0b1"), sha)
    for old in previous:
        run(repo, "git", "tag", old, sha)
    checkout = tmp_path / "checkout"
    output = tmp_path / "artifacts"
    run(tmp_path, "git", "clone", str(repo), str(checkout))
    run(checkout, "git", "config", "tag.gpgsign", "false")
    monkeypatch.chdir(checkout)
    release.prepare(sha, "rc", output, remote=False)
    assert release.validate_artifacts(output, sha, "rc") == (tag, previous)
    assert run(checkout, "git", "rev-parse", tag) == sha
    assert run(checkout, "git", "tag", "--list") == tag
    notes = (output / "release-notes.md").read_text("utf-8")
    assert tag in notes
    assert "initial package" in notes
    assert not (checkout / "CHANGELOG.md").exists()
    # Our preparation must not publish tags or alter the source repository.
    assert set(run(repo, "git", "tag", "--list").splitlines()) == set(previous)
    for published, target in previous.items():
        assert run(repo, "git", "rev-parse", published) == target


@pytest.mark.portable
def test_tagged_package_smoke(repo: Path) -> None:
    # Verify our package configuration and the actual isolated sdist-to-wheel
    # build/install helper at one release tag, without running release
    # orchestration again.
    run(repo, "git", "tag", "v0.1.0rc1")
    run(repo, sys.executable, "scripts/check_package.py")
    assert (repo / "dist/muteinous-0.1.0rc1.tar.gz").is_file()
    assert (repo / "dist/muteinous-0.1.0rc1-py3-none-any.whl").is_file()


def test_development_artifacts_have_provenance(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_synthetic_package_build(monkeypatch)
    monkeypatch.chdir(repo)
    sha = run(repo, "git", "rev-parse", "HEAD")
    output = tmp_path / "dev-artifacts"
    release.build(sha, output)
    metadata = json.loads((output / "build-metadata.json").read_text("utf-8"))
    assert metadata["sha"] == sha
    assert metadata["tag"] is None
    assert ".dev" in metadata["version"]
    assert metadata["environment"]["lock_sha256"] == release.digest(repo / "uv.lock")
    for name, expected in metadata["artifacts"].items():
        assert release.digest(output / name) == expected
    for line in (output / "SHA256SUMS").read_text("utf-8").splitlines():
        expected, name = line.split("  ", 1)
        assert release.digest(output / name) == expected
    assert not run(repo, "git", "tag", "--list")
    with pytest.raises(RuntimeError, match="fresh output"):
        release.build(sha, output)


@pytest.mark.portable
def test_locked_build_backends_satisfy_declared_requirements() -> None:
    root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))
    for spec in config["build-system"]["requires"]:
        requirement = Requirement(spec)
        assert requirement.specifier.contains(version(requirement.name)), spec


@pytest.mark.portable
def test_configured_prerelease_numbering(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo)
    run(repo, "git", "tag", "v0.2.0")
    run(repo, "git", "commit", "--allow-empty", "-m", "fix: correct behavior")
    run(repo, "git", "tag", "v0.2.1a1")
    assert release.propose("alpha") == "v0.2.1a2"
    assert set(release.local_tags()) == {"v0.2.0", "v0.2.1a1"}
    assert run(repo, "git", "status", "--porcelain") == ""


@pytest.mark.portable
def test_actual_commitizen_one_point_zero_guard(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo)
    run(repo, "git", "tag", "v0.2.0")
    config = repo / "pyproject.toml"
    config.write_text(
        config.read_text("utf-8").replace(
            "major_version_zero = true", "major_version_zero = false"
        ),
        encoding="utf-8",
    )
    run(repo, "git", "add", "pyproject.toml")
    run(repo, "git", "commit", "-m", "feat!: change release policy in test")
    with pytest.raises(RuntimeError, match="reviewed policy"):
        release.propose("stable")
    assert run(repo, "git", "tag", "--list") == "v0.2.0"


@pytest.mark.portable
def test_release_history_starts_after_bootstrap(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo)
    run(repo, "git", "commit", "--allow-empty", "-m", "legacy nonconventional")
    run(
        repo, "git", "commit", "--allow-empty", "-m", "feat: establish history boundary"
    )
    bootstrap = run(repo, "git", "rev-parse", "HEAD")
    monkeypatch.setattr(release, "BOOTSTRAP", bootstrap)
    run(repo, "git", "commit", "--allow-empty", "-m", "fix: conventional afterwards")
    release.check_history()
    run(repo, "git", "commit", "--allow-empty", "-m", "Merge random changes")
    run(repo, "git", "commit", "--allow-empty", "-m", "fix: valid final message")
    with pytest.raises(RuntimeError, match="commitizen"):
        release.check_history()


@pytest.mark.portable
def test_build_refuses_stale_dist_and_prepare_refuses_remote_drift(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo)
    sha = run(repo, "git", "rev-parse", "HEAD")
    (repo / "dist").mkdir()
    (repo / "dist/stale.whl").write_bytes(b"stale")
    output = tmp_path / "artifacts"
    with pytest.raises(RuntimeError, match="fresh output"):
        release.build(sha, output)
    assert not output.exists()
    assert (repo / "dist/stale.whl").read_bytes() == b"stale"
    shutil.rmtree(repo / "dist")
    monkeypatch.setattr(release, "BOOTSTRAP", sha)
    monkeypatch.setattr(release, "remote_tags", lambda: {"v0.0.9": sha})
    with pytest.raises(RuntimeError, match="Remote tags changed"):
        release.prepare(sha, "alpha", output)
    assert not output.exists()
    assert not run(repo, "git", "tag", "--list")
