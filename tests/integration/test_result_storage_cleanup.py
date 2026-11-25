"""Result-storage integration tests for real filesystem boundaries."""

from __future__ import annotations

import errno
import json
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from muteinous.infrastructure.storage._filesystem import (
    StorageError,
    canonical_json,
    checked_directory,
)
from muteinous.infrastructure.storage.bundles import ResultStore
from muteinous.infrastructure.storage.staging import try_lock
from tests.support.storage import (
    IDENTITY,
    make_directory_link,
    publish,
    read,
    validate_domain,
)


@pytest.mark.portable
def test_cleanup_retains_stage_with_alternate_stream_from_enumerator(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    with store.stage("alternate-stream-seam") as stage:
        directory = stage.path.parent
        owner = directory / "owner.json"
        owner_bytes = owner.read_bytes()
        payload = stage.path / "sentinel.bin"
        payload.write_bytes(b"keep")

    def enumerate_streams(path: Path) -> tuple[str, ...]:
        if path == owner:
            return ("::$DATA", ":review:$DATA")
        return ("::$DATA",)

    monkeypatch.setattr(
        "muteinous.infrastructure.storage._filesystem._enumerate_streams",
        enumerate_streams,
    )
    report = store.cleanup_abandoned()

    assert directory.name not in report.removed
    reason = dict(report.retained)[directory.name]
    assert "alternate data stream" in reason
    assert directory.is_dir()
    assert owner.read_bytes() == owner_bytes
    assert payload.read_bytes() == b"keep"


# Define this real-NTFS case only on Windows rather than recording a skipped test
# on platforms that cannot create NTFS alternate data streams.
if sys.platform == "win32":

    def test_cleanup_retains_stage_with_real_windows_alternate_stream(
        store: ResultStore,
    ) -> None:
        with store.stage("alternate-stream-ntfs") as stage:
            directory = stage.path.parent
            owner = directory / "owner.json"
            owner_bytes = owner.read_bytes()
            payload = stage.path / "sentinel.bin"
            payload.write_bytes(b"keep")
            owner_stream = Path(f"{owner}:review")
            owner_stream.write_bytes(b"unhashed owner stream")
            assert owner_stream.read_bytes() == b"unhashed owner stream"

        report = store.cleanup_abandoned()

        assert directory.name not in report.removed
        reason = dict(report.retained)[directory.name]
        assert "alternate data stream" in reason
        assert directory.is_dir()
        assert owner.read_bytes() == owner_bytes
        assert owner_stream.read_bytes() == b"unhashed owner stream"
        assert payload.read_bytes() == b"keep"


@pytest.mark.portable
def test_cleanup_protects_live_owner_and_ambiguous_paths(store: ResultStore) -> None:
    with store.stage("inactive") as stage:
        abandoned = stage.path.parent
    with store.stage("ambiguous") as stage:
        ambiguous = stage.path.parent
    (ambiguous / "owner.json").write_bytes(b"invalid")
    unrelated = store.root / "staging" / "unrelated.txt"
    unrelated.write_bytes(b"user data")
    unmarked = store.root / "staging" / ("0" * 32)
    unmarked.mkdir()
    (unmarked / "file").write_bytes(b"unknown")
    with store.stage("active") as stage:
        active = stage.path.parent
        (stage.path / "payload.bin").write_bytes(b"live")
        # A separate process must respect the actual kernel lease.
        script = """
import sys
from pathlib import Path
from muteinous.infrastructure.storage.bundles import ResultStore
report = ResultStore(Path(sys.argv[1]), atomic_rename_supported=True).cleanup_abandoned()
print(repr(report.removed))
"""
        child = subprocess.run(
            [sys.executable, "-c", script, str(store.root)],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        assert abandoned.name in child.stdout
        assert not abandoned.exists()
        assert (active / "payload" / "payload.bin").read_bytes() == b"live"
        report = store.cleanup_abandoned()
        assert {name for name, _ in report.retained} == {
            active.name,
            ambiguous.name,
            unrelated.name,
            unmarked.name,
        }
        assert dict(report.retained)[active.name] == "Staging owner is active"
        assert unrelated.read_bytes() == b"user data"
        assert (unmarked / "file").read_bytes() == b"unknown"


@pytest.mark.portable
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("session", "not-a-token"),
        ("stage", "mismatch"),
        ("process", 0),
        ("job", ""),
        ("schema", True),
    ],
)
def test_cleanup_retains_canonical_invalid_ownership_markers(
    store: ResultStore, field: str, value: object
) -> None:
    with store.stage("invalid-marker") as stage:
        directory = stage.path.parent
        (stage.path / "sentinel").write_bytes(b"keep")
    marker_path = directory / "owner.json"
    marker = json.loads(marker_path.read_bytes())
    if field == "stage":
        value = "0" * 32 if directory.name != "0" * 32 else "1" * 32
    marker[field] = value
    raw = canonical_json(marker)
    marker_path.write_bytes(raw)
    (store.root / "stage-leases" / f"{directory.name}.lock").write_bytes(raw)

    report = store.cleanup_abandoned()
    assert directory.name not in report.removed
    assert "Invalid staging ownership marker" in dict(report.retained)[directory.name]
    assert (directory / "payload" / "sentinel").read_bytes() == b"keep"


@pytest.mark.portable
@pytest.mark.parametrize("job_id", [123, b"x", ["a"], ""])
def test_stage_rejects_invalid_job_identity_before_creating_stage_or_lease(
    store: ResultStore, job_id: object
) -> None:
    staging = store.root / "staging"
    leases = store.root / "stage-leases"
    staging_before = set(staging.iterdir())
    leases_before = set(leases.iterdir())

    with pytest.raises(ValueError, match="nonempty job identity"):
        with store.stage(cast(str, job_id)):
            pytest.fail("Invalid job identity yielded a writable stage")

    assert set(staging.iterdir()) == staging_before
    assert set(leases.iterdir()) == leases_before


@pytest.mark.portable
def test_stage_fails_closed_when_new_lease_cannot_be_acquired(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    staging = store.root / "staging"
    leases = store.root / "stage-leases"
    staging_before = set(staging.iterdir())
    leases_before = set(leases.iterdir())

    @contextmanager
    def refuse_lease(_path: Path, *, root: Path | None = None) -> Iterator[None]:
        assert root == store.root
        yield None

    monkeypatch.setattr(
        "muteinous.infrastructure.storage.staging.try_lock", refuse_lease
    )
    with pytest.raises(StorageError, match="could not be acquired"):
        with store.stage("lease-refused"):
            pytest.fail("Stage was yielded without an acquired lease")

    assert set(staging.iterdir()) == staging_before
    created_leases = set(leases.iterdir()) - leases_before
    assert len(created_leases) == 1
    (lease_path,) = created_leases
    assert lease_path.is_file()
    assert lease_path.read_bytes()


@pytest.mark.portable
def test_cleanup_without_atomic_support_preserves_abandoned_stage(
    store: ResultStore,
) -> None:
    with store.stage("unsupported-cleanup") as stage:
        directory = stage.path.parent
        sentinel = stage.path / "sentinel"
        sentinel.write_bytes(b"keep")
    unsupported = ResultStore(store.root)
    with pytest.raises(StorageError, match="lease semantics are not established"):
        unsupported.cleanup_abandoned()
    assert directory.is_dir()
    assert sentinel.read_bytes() == b"keep"


@pytest.mark.portable
def test_cleanup_unlink_failure_preserves_busy_error_and_allows_retry(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "muteinous.infrastructure.storage.bundles.SELECTION_GUARD_TIMEOUT_SECONDS",
        0.0,
        raising=False,
    )
    previous = publish(store)
    lock_path = store.root / "selection.lock"
    locked = threading.Event()
    release = threading.Event()
    holder_errors: list[BaseException] = []

    def hold_guard() -> None:
        try:
            with try_lock(lock_path) as held:
                if held is None:
                    raise AssertionError("Could not acquire test selection guard")
                locked.set()
                if not release.wait(5):
                    raise TimeoutError("Test did not release selection guard")
        except BaseException as exc:
            holder_errors.append(exc)

    holder = threading.Thread(target=hold_guard)
    holder.start()
    original_unlink = Path.unlink
    candidate_path: Path | None = None
    integrity_path: Path | None = None
    failed_unlinks: set[Path] = set()

    def fail_publisher_unlink(path: Path, *, missing_ok: bool = False) -> None:
        if path in {candidate_path, integrity_path} and path not in failed_unlinks:
            failed_unlinks.add(path)
            raise PermissionError(errno.EACCES, "publisher file is temporarily locked")
        original_unlink(path, missing_ok=missing_ok)

    try:
        assert locked.wait(5), "Test selection guard was not acquired"
        with store.stage("cleanup-retry") as stage:
            (stage.path / "payload.bin").write_bytes(b"retry-cleanup")
            candidate_path = stage.path.parent / "candidate.json"
            integrity_path = stage.path / "integrity.json"
            monkeypatch.setattr("pathlib.Path.unlink", fail_publisher_unlink)
            with pytest.raises(StorageError, match="busy"):
                store.publish(
                    stage,
                    "scan",
                    IDENTITY,
                    expected=previous,
                    is_current=lambda: True,
                    validate_domain=validate_domain,
                )
            assert candidate_path.exists()
            assert integrity_path.exists()
            assert {candidate_path, integrity_path} <= failed_unlinks
            release.set()
            holder.join(timeout=5)
            assert not holder.is_alive()
            assert not holder_errors
            selected = store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=previous,
                is_current=lambda: True,
                validate_domain=validate_domain,
            )
    finally:
        release.set()
        holder.join(timeout=5)
    assert not holder.is_alive()
    assert store.selection("scan") == selected
    assert read(store) == b"retry-cleanup"


@pytest.mark.portable
def test_crashed_process_releases_staging_lease(store: ResultStore) -> None:
    script = """
import os
import sys
from pathlib import Path
from muteinous.infrastructure.storage.bundles import ResultStore
store = ResultStore(Path(sys.argv[1]), atomic_rename_supported=True)
with store.stage("crash") as stage:
    (stage.path / "partial").write_bytes(b"incomplete")
    print(stage.path.parent.name, flush=True)
    os._exit(0)
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(store.root)],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    token = child.stdout.strip()
    assert (store.root / "staging" / token / "payload" / "partial").is_file()
    assert store.cleanup_abandoned().removed == (token,)
    assert store.selection("scan") is None


def test_missing_or_mismatched_lease_is_ambiguous(store: ResultStore) -> None:
    with store.stage("no-lease") as stage:
        abandoned = stage.path.parent
    (store.root / "stage-leases" / f"{abandoned.name}.lock").unlink()
    with store.stage("wrong-lease") as stage:
        mismatch = stage.path.parent
    (store.root / "stage-leases" / f"{mismatch.name}.lock").write_bytes(b"other")
    report = store.cleanup_abandoned()
    assert not report.removed
    assert {name for name, _ in report.retained} == {abandoned.name, mismatch.name}


@pytest.mark.portable
def test_cleanup_accepts_valid_marker_with_process_id_one(store: ResultStore) -> None:
    with store.stage("pid-one-owner") as stage:
        directory = stage.path.parent
        (stage.path / "sentinel.bin").write_bytes(b"keep until cleanup")

    marker_path = directory / "owner.json"
    marker = json.loads(marker_path.read_bytes())
    marker["process"] = 1
    raw = canonical_json(marker)
    marker_path.write_bytes(raw)
    (store.root / "stage-leases" / f"{directory.name}.lock").write_bytes(raw)

    report = store.cleanup_abandoned()

    assert directory.name in report.removed
    assert not directory.exists()


@pytest.mark.portable
def test_cleanup_removes_stage_crashed_after_candidate_manifest_write(
    store: ResultStore,
) -> None:
    previous = publish(store, b"previous")
    store.cleanup_abandoned()
    script = """
import os
import sys
from pathlib import Path
import muteinous.infrastructure.storage.bundles as storage_bundles
from muteinous.infrastructure.storage.bundles import ResultStore, ResultIdentity
store = ResultStore(Path(sys.argv[1]), atomic_rename_supported=True)
def exit_after_candidate(source, destination):
    candidate = Path(source).parent / "candidate.json"
    assert candidate.is_file()
    assert candidate.stat().st_size > 0
    os._exit(73)
storage_bundles.os.rename = exit_after_candidate
identity = ResultIdentity("source-a", "config-a", "generation-a")
with store.stage("crash-after-candidate") as stage:
    (stage.path / "payload.bin").write_bytes(b"candidate")
    print(stage.path.parent.name, flush=True)
    store.publish(
        stage,
        "scan",
        identity,
        expected=store.selection("scan"),
        is_current=lambda: True,
        validate_domain=lambda path: None,
    )
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(store.root)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert child.returncode == 73
    token = child.stdout.strip()
    assert token
    abandoned = store.root / "staging" / token
    assert (abandoned / "candidate.json").is_file()

    report = store.cleanup_abandoned()
    assert token in report.removed
    assert store.selection("scan") == previous
    assert read(store) == b"previous"


def test_cleanup_retains_unexpected_staging_root_entry(store: ResultStore) -> None:
    with store.stage("job") as stage:
        directory = stage.path.parent
        (stage.path / "payload.bin").write_bytes(b"incomplete")
    unrelated = directory / "unrelated.txt"
    unrelated.write_bytes(b"uncertain ownership")
    report = store.cleanup_abandoned()
    assert not report.removed
    assert {name for name, _ in report.retained} == {directory.name}
    assert unrelated.read_bytes() == b"uncertain ownership"


@pytest.mark.portable
def test_link_traversal_is_refused_for_publication_cleanup_and_reuse(
    store: ResultStore, tmp_path: Path
) -> None:
    first = publish(store)
    target = tmp_path / "unrelated"
    target.mkdir()
    (target / "keep").write_bytes(b"untouched")
    with store.stage("unsafe") as stage:
        directory = stage.path.parent
        (stage.path / "payload.bin").write_bytes(b"candidate")
        make_directory_link(stage.path / "escape", target)
        with pytest.raises(StorageError, match="Unsafe link"):
            store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=first,
                is_current=lambda: True,
                validate_domain=validate_domain,
            )
    report = store.cleanup_abandoned()
    assert directory.name in {name for name, _ in report.retained}
    assert (target / "keep").read_bytes() == b"untouched"
    assert read(store) == b"original"
    make_directory_link(store.root / "bundles" / first.bundle / "escape", target)
    with pytest.raises(StorageError, match="Unsafe link"):
        read(store)


@pytest.mark.portable
def test_store_root_under_linked_parent_works_and_cleans_up(
    tmp_path: Path,
) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    make_directory_link(linked_parent, real_parent)
    root = linked_parent / "store"
    root.mkdir()
    store = ResultStore(root, atomic_rename_supported=True)
    with store.stage("publish") as stage:
        stage_directory = stage.path.parent
        (stage.path / "payload.bin").write_bytes(b"root-under-link")
        store.publish(
            stage,
            "scan",
            IDENTITY,
            expected=None,
            is_current=lambda: True,
            validate_domain=validate_domain,
        )
    with store.open_current("scan", IDENTITY, validate_domain=validate_domain) as path:
        assert (path / "payload.bin").read_bytes() == b"root-under-link"
    report = store.cleanup_abandoned()
    assert stage_directory.name in report.removed
    assert (root / "stage-leases" / f"{stage_directory.name}.lock").is_file()


@pytest.mark.portable
def test_store_root_that_is_a_link_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    root_link = tmp_path / "root-link"
    make_directory_link(root_link, target)
    with pytest.raises(StorageError, match="Unsafe link"):
        ResultStore(root_link, atomic_rename_supported=True)


@pytest.mark.portable
@pytest.mark.parametrize("directory", ["bundles", "current", "staging", "stage-leases"])
def test_links_in_storage_directories_are_refused(
    tmp_path: Path, directory: str
) -> None:
    root = tmp_path / "store"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    make_directory_link(root / directory, outside)
    with pytest.raises(StorageError, match="Unsafe link"):
        ResultStore(root, atomic_rename_supported=True)


@pytest.mark.portable
def test_cleanup_retains_stage_on_another_device_with_payload_untouched(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    with store.stage("foreign-stage-device") as stage:
        directory = stage.path.parent
        sentinel = stage.path / "sentinel"
        sentinel.write_bytes(b"keep")
    original_checked_directory = checked_directory

    def foreign_stage_device(path: Path, *, root: Path | None = None) -> object:
        info = original_checked_directory(path, root=root)
        if path == directory:
            return SimpleNamespace(st_dev=info.st_dev + 1)
        return info

    monkeypatch.setattr(
        "muteinous.infrastructure.storage.staging.checked_directory",
        foreign_stage_device,
    )
    report = store.cleanup_abandoned()
    assert directory.name not in report.removed
    assert "another filesystem" in dict(report.retained)[directory.name]
    assert sentinel.read_bytes() == b"keep"
