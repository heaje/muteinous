"""Representative safety-critical result publication and recovery checks."""

from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import BinaryIO

import pytest

from muteinous.infrastructure.storage._filesystem import (
    InsufficientSpace,
    StorageError,
    canonical_json,
    checked_directory,
    checked_stat,
    digest,
)
from muteinous.infrastructure.storage.bundles import (
    ResultIdentity,
    ResultStore,
    Selection,
)
from muteinous.infrastructure.storage.space import (
    SpaceRequirement,
    preflight,
    translate_write_error,
)
from muteinous.infrastructure.storage.staging import try_lock

IDENTITY = ResultIdentity("source-a", "config-a", "generation-a")


def validate_domain(path: Path) -> None:
    if not (path / "payload.bin").is_file():
        raise StorageError("Domain requires a payload")


@pytest.fixture
def store(tmp_path: Path) -> ResultStore:
    return ResultStore(tmp_path, atomic_rename_supported=True)


def publish(store: ResultStore, data: bytes = b"original") -> Selection:
    expected = store.selection("scan")
    with store.stage("job") as stage:
        (stage.path / "payload.bin").write_bytes(data)
        return store.publish(
            stage,
            "scan",
            IDENTITY,
            expected=expected,
            is_current=lambda: True,
            validate_domain=validate_domain,
        )


def read(store: ResultStore, identity: ResultIdentity = IDENTITY) -> bytes:
    with store.open_current("scan", identity, validate_domain=validate_domain) as path:
        return (path / "payload.bin").read_bytes()


@pytest.mark.portable
def test_partial_stage_never_becomes_current_and_old_reader_is_safe(
    store: ResultStore,
) -> None:
    with store.stage("incomplete") as area:
        (area.path / "payload.bin").write_bytes(b"partial")
        assert store.selection("scan") is None
        with pytest.raises(StorageError, match="No committed"):
            read(store)
    first = publish(store)
    with store.open_current("scan", IDENTITY, validate_domain=validate_domain) as old:
        assert old.name == first.bundle
        with store.stage("replacement-in-progress") as area:
            (area.path / "payload.bin").write_bytes(b"incomplete")
            assert read(store) == b"original"
        publish(store, b"replacement")
        store.cleanup_abandoned()
        assert (old / "payload.bin").read_bytes() == b"original"
        assert read(store) == b"replacement"


@pytest.mark.portable
@pytest.mark.parametrize("operation", ["rename", "replace"])
def test_atomic_operation_failure_preserves_previous_selection(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    first = publish(store)

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError(errno.ENOTSUP, "atomic operation unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(f"muteinous.infrastructure.storage.bundles.os.{operation}", fail)
        with pytest.raises(OSError, match="atomic operation unavailable"):
            publish(store, b"replacement")
    assert store.selection("scan") == first
    assert read(store) == b"original"
    # Failed manifest switch leaves a complete but unreferenced candidate.
    assert len(list((store.root / "bundles").iterdir())) == (
        2 if operation == "replace" else 1
    )


@pytest.mark.portable
def test_unknown_atomic_support_refuses_without_modifying_current(
    store: ResultStore,
) -> None:
    first = publish(store)
    unsupported = ResultStore(store.root)
    with pytest.raises(StorageError, match="Atomic publication"):
        publish(unsupported, b"replacement")
    assert store.selection("scan") == first
    assert read(store) == b"original"


def test_interrupt_after_directory_rename_before_manifest_switch(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = publish(store)

    class Interrupted(BaseException):
        pass

    def interrupt(*args: object, **kwargs: object) -> None:
        raise Interrupted()

    with monkeypatch.context() as patch:
        patch.setattr("muteinous.infrastructure.storage.bundles.os.replace", interrupt)
        with pytest.raises(Interrupted):
            publish(store, b"candidate")
    restarted = ResultStore(store.root, atomic_rename_supported=True)
    restarted.cleanup_abandoned()
    assert restarted.selection("scan") == first
    assert read(restarted) == b"original"
    assert len(list((store.root / "bundles").iterdir())) == 2


@pytest.mark.portable
def test_rename_then_base_exception_consumes_stage_without_changing_current(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = publish(store)
    real_rename = os.rename

    class InterruptedAfterRename(BaseException):
        pass

    def rename_then_interrupt(source: Path, destination: Path) -> None:
        real_rename(source, destination)
        raise InterruptedAfterRename()

    with store.stage("interrupt-after-rename") as stage:
        (stage.path / "payload.bin").write_bytes(b"candidate")
        monkeypatch.setattr(
            "muteinous.infrastructure.storage.bundles.os.rename",
            rename_then_interrupt,
        )
        with pytest.raises(InterruptedAfterRename):
            store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=previous,
                is_current=lambda: True,
                validate_domain=validate_domain,
            )
        with pytest.raises(StorageError, match="no longer writable"):
            _ = stage.path
        with pytest.raises(StorageError, match="no longer writable"):
            store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=previous,
                is_current=lambda: True,
                validate_domain=validate_domain,
            )
    assert store.selection("scan") == previous
    assert read(store) == b"original"
    assert len(list((store.root / "bundles").iterdir())) == 2


@pytest.mark.portable
def test_stale_producer_and_final_generation_change_cannot_win(
    store: ResultStore,
) -> None:
    first = publish(store)
    with store.stage("older") as older:
        (older.path / "payload.bin").write_bytes(b"older")
        second = publish(store, b"newer")
        with pytest.raises(StorageError, match="superseded"):
            store.publish(
                older,
                "scan",
                IDENTITY,
                expected=first,
                is_current=lambda: True,
                validate_domain=validate_domain,
            )
        assert not (older.path / "integrity.json").exists()
        assert not (older.path.parent / "candidate.json").exists()
        assert (older.path / "payload.bin").read_bytes() == b"older"
    with store.stage("changed-generation") as stage:
        (stage.path / "payload.bin").write_bytes(b"stale")
        checks = iter([True, False])
        with pytest.raises(StorageError, match="superseded"):
            store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=second,
                is_current=lambda: next(checks),
                validate_domain=validate_domain,
            )
    assert store.selection("scan") == second
    assert read(store) == b"newer"


@pytest.mark.portable
@pytest.mark.parametrize("damage", ["missing", "extra", "altered", "empty-directory"])
def test_reuse_rehashes_and_refuses_damaged_exact_bundle(
    store: ResultStore, damage: str
) -> None:
    publish(store, b"previous")
    selection = publish(store)
    assert read(store) == b"original"
    path = store.root / "bundles" / selection.bundle
    member = path / "payload.bin"
    if damage == "missing":
        member.unlink()
    elif damage == "extra":
        (path / "extra").write_bytes(b"unexpected")
    elif damage == "altered":
        before = member.stat()
        member.write_bytes(b"changed!")
        os.utime(member, ns=(before.st_atime_ns, before.st_mtime_ns))
    else:
        (path / "empty").mkdir()
    # No cached verdict, even when changed bytes retain length and mtime.
    with pytest.raises(StorageError):
        read(store)
    with pytest.raises(StorageError):
        read(ResultStore(store.root, atomic_rename_supported=True))


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema", True),
        ("schema", 2),
        ("source", "other"),
        ("files", [{"path": "../payload.bin", "length": 8, "sha256": "0" * 64}]),
        ("files", []),
    ],
)
def test_invalid_metadata_is_rejected_even_if_manifest_digest_matches(
    store: ResultStore, field: str, value: object
) -> None:
    selection = publish(store)
    path = store.root / "bundles" / selection.bundle / "integrity.json"
    metadata = json.loads(path.read_bytes())
    metadata[field] = value
    raw = canonical_json(metadata)
    path.write_bytes(raw)
    manifest = store.root / "current" / "scan.json"
    manifest.write_bytes(
        canonical_json(
            {"schema": 1, "bundle": selection.bundle, "metadata_sha256": digest(raw)}
        )
    )
    with pytest.raises(StorageError):
        read(store)


@pytest.mark.parametrize("damage", ["missing", "unsafe", "digest", "noncanonical"])
def test_current_manifest_is_authoritative_without_fallback(
    store: ResultStore, damage: str
) -> None:
    publish(store, b"old")
    selection = publish(store)
    path = store.root / "current" / "scan.json"
    if damage == "missing":
        path.unlink()
    elif damage == "noncanonical":
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        path.write_bytes(
            canonical_json(
                {
                    "schema": 1,
                    "bundle": "../staging" if damage == "unsafe" else selection.bundle,
                    "metadata_sha256": "0" * 64,
                }
            )
        )
    with pytest.raises(StorageError):
        read(ResultStore(store.root, atomic_rename_supported=True))


@pytest.mark.parametrize(
    "identity",
    [
        ResultIdentity("different-source", "config-a", "generation-a"),
        ResultIdentity("source-a", "different-config", "generation-a"),
        ResultIdentity("source-a", "config-a", "different-generation"),
    ],
)
def test_source_configuration_and_generation_are_required_on_every_reuse(
    store: ResultStore, identity: ResultIdentity
) -> None:
    publish(store)
    assert read(store) == b"original"
    with pytest.raises(StorageError):
        read(store, identity)


def test_domain_failure_prevents_publication_and_reuse(store: ResultStore) -> None:
    first = publish(store)

    def reject(path: Path) -> None:
        raise StorageError("Domain validation refused")

    with store.stage("invalid") as stage:
        (stage.path / "payload.bin").write_bytes(b"invalid")
        with pytest.raises(StorageError, match="Domain validation"):
            store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=first,
                is_current=lambda: True,
                validate_domain=reject,
            )
    assert store.selection("scan") == first
    with pytest.raises(StorageError, match="Domain validation"):
        with store.open_current("scan", IDENTITY, validate_domain=reject):
            pytest.fail("Invalid domain result was exposed")


@pytest.mark.portable
def test_pre_rename_domain_refusal_leaves_stage_retryable(store: ResultStore) -> None:
    previous = publish(store)
    calls = 0

    def reject_once(path: Path) -> None:
        nonlocal calls
        calls += 1
        validate_domain(path)
        if calls == 1:
            raise StorageError("Temporary domain validation refusal")

    with store.stage("domain-retry") as stage:
        (stage.path / "payload.bin").write_bytes(b"retry-after-domain")
        with pytest.raises(StorageError, match="Temporary domain"):
            store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=previous,
                is_current=lambda: True,
                validate_domain=reject_once,
            )
        assert not (stage.path / "integrity.json").exists()
        assert not (stage.path.parent / "candidate.json").exists()
        assert (stage.path / "payload.bin").read_bytes() == b"retry-after-domain"
        selected = store.publish(
            stage,
            "scan",
            IDENTITY,
            expected=previous,
            is_current=lambda: True,
            validate_domain=validate_domain,
        )
    assert store.selection("scan") == selected
    assert read(store) == b"retry-after-domain"


@pytest.mark.portable
def test_slow_open_validation_does_not_hold_selection_guard(store: ResultStore) -> None:
    selection = publish(store)
    validating = threading.Event()
    continue_validation = threading.Event()

    def slow_validator(path: Path) -> None:
        validate_domain(path)
        validating.set()
        if not continue_validation.wait(5):
            raise TimeoutError("Test did not release slow validation")

    def slow_open() -> bytes:
        with store.open_current(
            "scan", IDENTITY, validate_domain=slow_validator
        ) as path:
            return (path / "payload.bin").read_bytes()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(slow_open)
        assert validating.wait(5), "Open validation did not start"
        try:
            assert store.selection("scan") == selection
            with store.open_current(
                "scan", IDENTITY, validate_domain=validate_domain
            ) as path:
                assert (path / "payload.bin").read_bytes() == b"original"
        finally:
            continue_validation.set()
        assert future.result(timeout=5) == b"original"


@pytest.mark.portable
def test_slow_publish_validation_does_not_hold_selection_guard(
    store: ResultStore,
) -> None:
    previous = publish(store)
    validating = threading.Event()
    continue_validation = threading.Event()

    def publish_slowly() -> Selection:
        calls = 0

        def slow_validator(path: Path) -> None:
            nonlocal calls
            calls += 1
            validate_domain(path)
            if calls == 2:
                validating.set()
                if not continue_validation.wait(5):
                    raise TimeoutError("Test did not release slow validation")

        with store.stage("slow-publish") as stage:
            (stage.path / "payload.bin").write_bytes(b"candidate")
            return store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=previous,
                is_current=lambda: True,
                validate_domain=slow_validator,
            )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(publish_slowly)
        assert validating.wait(5), "Committed-bundle validation did not start"
        try:
            assert store.selection("scan") == previous
        finally:
            continue_validation.set()
        selected = future.result(timeout=5)
    assert store.selection("scan") == selected
    assert read(store) == b"candidate"


@pytest.mark.portable
def test_publish_racing_with_open_recheck_refuses_stale_open(
    store: ResultStore,
) -> None:
    old = publish(store)
    validating = threading.Event()
    continue_validation = threading.Event()

    def slow_validator(path: Path) -> None:
        validate_domain(path)
        validating.set()
        if not continue_validation.wait(5):
            raise TimeoutError("Test did not release slow validation")

    def slow_open() -> None:
        with store.open_current("scan", IDENTITY, validate_domain=slow_validator):
            pass

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(slow_open)
        assert validating.wait(5), "Open validation did not start"
        try:
            new = publish(store, b"new-current")
        finally:
            continue_validation.set()
        with pytest.raises(StorageError, match="selection changed"):
            future.result(timeout=5)
    assert new != old
    assert store.selection("scan") == new
    assert read(store) == b"new-current"


@pytest.mark.portable
def test_selection_guard_waits_for_brief_contention(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = publish(store)
    contended = threading.Event()
    acquired = threading.Event()
    holder_errors: list[BaseException] = []
    original_try_lock = try_lock

    @contextmanager
    def observe_contention(
        path: Path, *, root: Path | None = None
    ) -> Iterator[BinaryIO | None]:
        with original_try_lock(path, root=root) as held:
            if held is None:
                contended.set()
            yield held

    monkeypatch.setattr(
        "muteinous.infrastructure.storage.bundles.try_lock", observe_contention
    )

    def hold_until_contended() -> None:
        try:
            with original_try_lock(store.root / "selection.lock") as held:
                if held is None:
                    raise AssertionError("Could not acquire test selection guard")
                acquired.set()
                if not contended.wait(5):
                    raise TimeoutError("Selection operation did not observe contention")
        except BaseException as exc:
            holder_errors.append(exc)

    holder = threading.Thread(target=hold_until_contended)
    holder.start()
    try:
        assert acquired.wait(5), "Test selection guard was not acquired"
        assert store.selection("scan") == previous
    finally:
        contended.set()
        holder.join(timeout=5)
    assert not holder.is_alive()
    assert not holder_errors


@pytest.mark.portable
def test_publish_waits_through_brief_final_guard_contention(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = publish(store)
    validating = threading.Event()
    continue_validation = threading.Event()
    contended = threading.Event()
    guard_acquired = threading.Event()
    holder_errors: list[BaseException] = []
    original_try_lock = try_lock

    @contextmanager
    def observe_contention(
        path: Path, *, root: Path | None = None
    ) -> Iterator[BinaryIO | None]:
        with original_try_lock(path, root=root) as held:
            if held is None:
                contended.set()
            yield held

    monkeypatch.setattr(
        "muteinous.infrastructure.storage.bundles.try_lock", observe_contention
    )

    def publish_slowly() -> Selection:
        calls = 0

        def slow_validator(path: Path) -> None:
            nonlocal calls
            calls += 1
            validate_domain(path)
            if calls == 2:
                validating.set()
                if not continue_validation.wait(5):
                    raise TimeoutError("Test did not release post-rename validation")

        with store.stage("brief-final-contention") as stage:
            (stage.path / "payload.bin").write_bytes(b"published-after-wait")
            return store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=previous,
                is_current=lambda: True,
                validate_domain=slow_validator,
            )

    def hold_final_guard_until_contended() -> None:
        try:
            with original_try_lock(store.root / "selection.lock") as held:
                if held is None:
                    raise AssertionError("Could not acquire final selection guard")
                guard_acquired.set()
                if not contended.wait(5):
                    raise TimeoutError("Publish did not observe final-guard contention")
        except BaseException as exc:
            holder_errors.append(exc)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(publish_slowly)
        assert validating.wait(5), "Committed-bundle validation did not start"
        holder = threading.Thread(target=hold_final_guard_until_contended)
        holder.start()
        try:
            assert guard_acquired.wait(5), "Final selection guard was not acquired"
            continue_validation.set()
            selected = future.result(timeout=5)
        finally:
            continue_validation.set()
            contended.set()
            holder.join(timeout=5)
        assert not holder.is_alive()
        assert not holder_errors
    assert store.selection("scan") == selected
    assert len(list((store.root / "bundles").iterdir())) == 2
    assert read(store) == b"published-after-wait"


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
def test_empty_selection_guard_is_initialized_and_usable(tmp_path: Path) -> None:
    (tmp_path / "selection.lock").touch()
    store = ResultStore(tmp_path, atomic_rename_supported=True)
    assert store.selection("scan") is None
    selected = publish(store)
    assert store.selection("scan") == selected
    with store.open_current("scan", IDENTITY, validate_domain=validate_domain) as path:
        assert (path / "payload.bin").read_bytes() == b"original"


@pytest.mark.portable
def test_busy_publish_can_retry_with_the_same_stage(
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
    try:
        assert locked.wait(5), "Test selection guard was not acquired"
        with store.stage("retry") as stage:
            (stage.path / "payload.bin").write_bytes(b"retry")
            with pytest.raises(StorageError, match="busy"):
                store.publish(
                    stage,
                    "scan",
                    IDENTITY,
                    expected=previous,
                    is_current=lambda: True,
                    validate_domain=validate_domain,
                )
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
    assert read(store) == b"retry"


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
    fail_once = [True]

    def fail_candidate_unlink(path: Path, *, missing_ok: bool = False) -> None:
        if path == candidate_path and fail_once[0]:
            fail_once[0] = False
            raise PermissionError(errno.EACCES, "candidate is temporarily locked")
        original_unlink(path, missing_ok=missing_ok)

    try:
        assert locked.wait(5), "Test selection guard was not acquired"
        with store.stage("cleanup-retry") as stage:
            (stage.path / "payload.bin").write_bytes(b"retry-cleanup")
            candidate_path = stage.path.parent / "candidate.json"
            monkeypatch.setattr("pathlib.Path.unlink", fail_candidate_unlink)
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
            assert not (stage.path / "integrity.json").exists()
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
def test_producer_supplied_integrity_file_is_refused_untouched(
    store: ResultStore,
) -> None:
    supplied = b"producer data"
    with store.stage("reserved-metadata") as stage:
        (stage.path / "payload.bin").write_bytes(b"payload")
        integrity = stage.path / "integrity.json"
        integrity.write_bytes(supplied)
        with pytest.raises(StorageError, match="integrity"):
            store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=None,
                is_current=lambda: True,
                validate_domain=validate_domain,
            )
        assert integrity.read_bytes() == supplied
        assert not (stage.path.parent / "candidate.json").exists()
    assert store.selection("scan") is None


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


def make_directory_link(link: Path, target: Path) -> None:
    if sys.platform == "win32":
        # NTFS junctions do not require the symlink-creation privilege.
        subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
            timeout=10,
        )
    else:
        link.symlink_to(target, target_is_directory=True)


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


def test_hardlinked_payload_is_refused(store: ResultStore, tmp_path: Path) -> None:
    target = tmp_path / "unrelated.bin"
    target.write_bytes(b"untouched")
    with store.stage("hardlink") as stage:
        os.link(target, stage.path / "payload.bin")
        with pytest.raises(StorageError, match="Unexpected filesystem entry"):
            store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=None,
                is_current=lambda: True,
                validate_domain=validate_domain,
            )
    assert target.read_bytes() == b"untouched"
    assert store.selection("scan") is None


@pytest.mark.portable
def test_preflight_known_minimum_unknown_estimate_and_aggregation(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = publish(store)
    monkeypatch.setattr(
        "muteinous.infrastructure.storage.space.shutil.disk_usage",
        lambda path: SimpleNamespace(free=10),
    )
    with pytest.raises(InsufficientSpace):
        with store.stage("too-large", minimum_bytes=11):
            pytest.fail("Known shortage was ignored")
    with pytest.raises(InsufficientSpace):
        preflight(
            [
                SpaceRequirement(store.root, 6),
                SpaceRequirement(store.root / "staging", 5),
            ]
        )
    with store.stage("unknown-size", minimum_bytes=5) as stage:
        assert stage.space_assessments[0].uncertain
        assert stage.space_assessments[0].minimum == 5
        (stage.path / "payload.bin").write_bytes(b"test")
        with pytest.raises(InsufficientSpace):
            store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=first,
                is_current=lambda: True,
                validate_domain=validate_domain,
            )
    assert store.selection("scan") == first
    assert read(store) == b"original"


@pytest.mark.portable
@pytest.mark.parametrize(
    ("estimates", "available", "expected", "uncertain"),
    [
        ((4, 7), 10, 11, True),
        ((4, 5), 10, 9, False),
    ],
)
def test_preflight_sums_finite_estimates_and_reports_uncertainty(
    store: ResultStore,
    monkeypatch: pytest.MonkeyPatch,
    estimates: tuple[int, int],
    available: int,
    expected: int,
    uncertain: bool,
) -> None:
    monkeypatch.setattr(
        "muteinous.infrastructure.storage.space.shutil.disk_usage",
        lambda path: SimpleNamespace(free=available),
    )
    (assessment,) = preflight(
        [
            SpaceRequirement(store.root, 1, estimates[0]),
            SpaceRequirement(store.root / "staging", 1, estimates[1]),
        ]
    )
    assert assessment.estimate == expected
    assert assessment.uncertain is uncertain


@pytest.mark.portable
@pytest.mark.parametrize("winerror", [39, 112, 1295])
def test_windows_disk_full_errors_are_classified_as_insufficient_space(
    winerror: int,
) -> None:
    error = OSError(errno.EINVAL, "Windows disk capacity error")
    setattr(error, "winerror", winerror)
    with pytest.raises(InsufficientSpace) as exc:
        translate_write_error(error)
    assert exc.value.__cause__ is error


@pytest.mark.portable
def test_edquot_is_classified_as_insufficient_space_when_available() -> None:
    quota_errno = getattr(errno, "EDQUOT", None)
    if quota_errno is not None:
        with pytest.raises(InsufficientSpace):
            translate_write_error(OSError(quota_errno, "disk quota exceeded"))


@pytest.mark.portable
def test_preflight_measurement_failure_creates_no_stage_and_preserves_current(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = publish(store)
    store.cleanup_abandoned()
    staging_before = set((store.root / "staging").iterdir())
    leases_before = set((store.root / "stage-leases").iterdir())

    def fail_measurement(path: Path) -> SimpleNamespace:
        raise OSError(errno.EIO, "space measurement unavailable")

    monkeypatch.setattr(
        "muteinous.infrastructure.storage.space.shutil.disk_usage",
        fail_measurement,
    )
    with pytest.raises(StorageError, match="Cannot establish available space"):
        with store.stage("space-measurement-failure"):
            pytest.fail("Stage was created without a space assessment")
    assert set((store.root / "staging").iterdir()) == staging_before
    assert set((store.root / "stage-leases").iterdir()) == leases_before
    assert store.selection("scan") == previous
    assert read(store) == b"original"


@pytest.mark.portable
def test_runtime_disk_full_after_successful_preflight_preserves_current(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = publish(store)
    with pytest.raises(InsufficientSpace):
        with store.stage("write-failure", minimum_bytes=1) as stage:
            (stage.path / "payload.bin").write_bytes(b"partial")
            raise OSError(errno.ENOSPC, "disk full")

    def disk_full(*args: object, **kwargs: object) -> None:
        raise OSError(errno.ENOSPC, "disk full during manifest switch")

    with monkeypatch.context() as patch:
        patch.setattr("muteinous.infrastructure.storage.bundles.os.replace", disk_full)
        with pytest.raises(InsufficientSpace):
            publish(store, b"replacement")
    assert store.selection("scan") == first
    store.cleanup_abandoned()
    assert read(store) == b"original"


def test_domain_failure_after_rename_preserves_current(store: ResultStore) -> None:
    first = publish(store)
    checks = iter([True, False])

    def validate(path: Path) -> None:
        validate_domain(path)
        if not next(checks):
            raise StorageError("Post-rename validation refused")

    with store.stage("invalid-after-rename") as stage:
        (stage.path / "payload.bin").write_bytes(b"candidate")
        with pytest.raises(StorageError, match="Post-rename"):
            store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=first,
                is_current=lambda: True,
                validate_domain=validate,
            )
    assert store.selection("scan") == first
    assert read(store) == b"original"


def test_unknown_upper_bound_can_publish_when_space_is_available(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "muteinous.infrastructure.storage.space.shutil.disk_usage",
        lambda path: SimpleNamespace(free=1024 * 1024),
    )
    with store.stage("unknown-size", minimum_bytes=1) as stage:
        assert stage.space_assessments[0].uncertain
        (stage.path / "payload.bin").write_bytes(b"complete")
        store.publish(
            stage,
            "scan",
            IDENTITY,
            expected=None,
            is_current=lambda: True,
            validate_domain=validate_domain,
        )
    assert read(store) == b"complete"


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
def test_publication_refuses_mismatched_filesystem_before_rename(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = publish(store)
    real_checked_directory = checked_directory
    rename_calls: list[tuple[object, ...]] = []

    def different_current_device(path: Path, *, root: Path | None = None) -> object:
        info = real_checked_directory(path, root=root)
        if path == store.root / "current":
            return SimpleNamespace(st_dev=info.st_dev + 1)
        return info

    monkeypatch.setattr(
        "muteinous.infrastructure.storage.bundles.checked_directory",
        different_current_device,
    )

    def record_rename(*args: object) -> None:
        rename_calls.append(args)

    monkeypatch.setattr(
        "muteinous.infrastructure.storage.bundles.os.rename", record_rename
    )
    with store.stage("different-device") as stage:
        (stage.path / "payload.bin").write_bytes(b"candidate")
        with pytest.raises(StorageError, match="destination-filesystem"):
            store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=previous,
                is_current=lambda: True,
                validate_domain=validate_domain,
            )
    assert not rename_calls
    assert store.selection("scan") == previous
    assert read(store) == b"original"


@pytest.mark.portable
def test_publication_rejects_payload_file_on_another_device(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = publish(store)
    original_checked_stat = checked_stat
    payload: Path | None = None

    def foreign_payload_device(path: Path, *, directory: bool) -> object:
        info = original_checked_stat(path, directory=directory)
        if path == payload and not directory:
            return SimpleNamespace(
                st_size=info.st_size,
                st_mtime_ns=info.st_mtime_ns,
                st_ctime_ns=info.st_ctime_ns,
                st_ino=info.st_ino,
                st_dev=info.st_dev + 1,
            )
        return info

    with store.stage("foreign-payload-device") as stage:
        payload = stage.path / "payload.bin"
        payload.write_bytes(b"candidate")
        monkeypatch.setattr(
            "muteinous.infrastructure.storage._filesystem.checked_stat",
            foreign_payload_device,
        )
        with pytest.raises(StorageError, match="filesystem boundary"):
            store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=previous,
                is_current=lambda: True,
                validate_domain=validate_domain,
            )
    assert store.selection("scan") == previous
    assert len(list((store.root / "bundles").iterdir())) == 1
    assert read(store) == b"original"


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


@pytest.mark.portable
@pytest.mark.parametrize("failure", [errno.EXDEV, errno.ENOSPC])
def test_directory_rename_failure_preserves_current(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch, failure: int
) -> None:
    first = publish(store)

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError(failure, "cannot rename")

    with monkeypatch.context() as patch:
        patch.setattr("muteinous.infrastructure.storage.bundles.os.rename", fail)
        if failure == errno.ENOSPC:
            with pytest.raises(InsufficientSpace):
                publish(store, b"candidate")
        else:
            with pytest.raises(OSError) as exc:
                publish(store, b"candidate")
            assert exc.value.errno == failure
    assert store.selection("scan") == first
    assert read(store) == b"original"
