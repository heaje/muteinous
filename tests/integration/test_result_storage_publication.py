"""Result-storage integration tests for real filesystem boundaries."""

from __future__ import annotations

import errno
import hashlib
import os
import sys
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import BinaryIO

import pytest

import muteinous.infrastructure.storage._filesystem as storage_filesystem
import muteinous.infrastructure.storage.bundles as storage_bundles
from muteinous.infrastructure.storage._filesystem import InsufficientSpace, StorageError
from muteinous.infrastructure.storage.bundles import (
    ResultStore,
    Selection,
    UnreadableSelection,
)
from muteinous.infrastructure.storage.staging import try_lock
from tests.support.storage import IDENTITY, publish, read, validate_domain


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
def test_successful_publish_consumes_stage_inside_owning_context(
    store: ResultStore,
) -> None:
    expected = store.selection("scan")
    with store.stage("successful-publish") as stage:
        (stage.path / "payload.bin").write_bytes(b"published")
        selected = store.publish(
            stage,
            "scan",
            IDENTITY,
            expected=expected,
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
                expected=selected,
                is_current=lambda: True,
                validate_domain=validate_domain,
            )
    assert store.selection("scan") == selected
    assert read(store) == b"published"


@pytest.mark.portable
def test_stage_preserves_oserror_after_manifest_commit(store: ResultStore) -> None:
    error = OSError(errno.ENOSPC, "caller failed after publication")
    with pytest.raises(OSError) as raised:
        with store.stage("post-commit-caller-error") as stage:
            (stage.path / "payload.bin").write_bytes(b"committed")
            selected = store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=None,
                is_current=lambda: True,
                validate_domain=validate_domain,
            )
            raise error

    assert raised.value is error
    assert store.selection("scan") == selected
    assert read(store) == b"committed"


@pytest.mark.portable
def test_interruption_after_manifest_replace_uses_new_selection_and_consumes_stage(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = publish(store, b"previous")
    manifest = store.root / "current" / "scan.json"
    original_replace = os.replace
    interruption = KeyboardInterrupt()

    def replace_then_interrupt(
        source: str | os.PathLike[str], destination: str | os.PathLike[str]
    ) -> None:
        original_replace(source, destination)
        if Path(destination) == manifest:
            raise interruption

    with store.stage("interrupted-after-commit") as stage:
        (stage.path / "payload.bin").write_bytes(b"committed-before-interruption")
        with monkeypatch.context() as patch:
            patch.setattr(os, "replace", replace_then_interrupt)
            with pytest.raises(KeyboardInterrupt) as raised:
                store.publish(
                    stage,
                    "scan",
                    IDENTITY,
                    expected=previous,
                    is_current=lambda: True,
                    validate_domain=validate_domain,
                )
        assert raised.value is interruption
        with pytest.raises(StorageError, match="no longer writable"):
            _ = stage.path

    selected = store.selection("scan")
    assert selected is not None and selected != previous
    assert read(store) == b"committed-before-interruption"
    with store.open_current("scan", IDENTITY, validate_domain=validate_domain) as path:
        assert (path / "payload.bin").read_bytes() == b"committed-before-interruption"
    with pytest.raises(StorageError, match="no longer writable"):
        store.publish(
            stage,
            "scan",
            IDENTITY,
            expected=selected,
            is_current=lambda: True,
            validate_domain=validate_domain,
        )


@pytest.mark.portable
def test_nonspace_manifest_replace_error_propagates_and_preserves_selection(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = publish(store, b"previous")
    error = OSError(errno.EIO, "injected manifest replacement I/O failure")

    def fail_replace(
        source: str | os.PathLike[str], destination: str | os.PathLike[str]
    ) -> None:
        if Path(destination) == store.root / "current" / "scan.json":
            raise error
        os.replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", fail_replace)
        with pytest.raises(OSError) as raised:
            publish(store, b"replacement")

    assert type(raised.value) is OSError
    assert raised.value.errno == errno.EIO
    assert raised.value is error
    assert not isinstance(raised.value, InsufficientSpace)
    assert store.selection("scan") == previous
    assert read(store) == b"previous"


@pytest.mark.portable
def test_stage_after_context_exit_cannot_be_published(store: ResultStore) -> None:
    expected = store.selection("scan")
    with store.stage("closed-stage") as stage:
        (stage.path / "payload.bin").write_bytes(b"closed")

    with pytest.raises(StorageError, match="no longer writable"):
        _ = stage.path
    with pytest.raises(StorageError, match="no longer writable"):
        store.publish(
            stage,
            "scan",
            IDENTITY,
            expected=expected,
            is_current=lambda: True,
            validate_domain=validate_domain,
        )
    assert store.selection("scan") == expected


@pytest.mark.portable
def test_bundle_id_collision_leaves_stage_retryable(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = publish(store, b"previous")
    bundle_id = "a" * 32
    (store.root / "bundles" / bundle_id).mkdir()

    with store.stage("bundle-collision") as stage:
        (stage.path / "payload.bin").write_bytes(b"retry")
        with monkeypatch.context() as patch:
            patch.setattr(
                storage_bundles,
                "uuid4",
                lambda: SimpleNamespace(hex=bundle_id),
            )
            with pytest.raises(StorageError, match="Bundle identity already exists"):
                store.publish(
                    stage,
                    "scan",
                    IDENTITY,
                    expected=previous,
                    is_current=lambda: True,
                    validate_domain=validate_domain,
                )
        assert stage.path.is_dir()
        assert (stage.path / "payload.bin").read_bytes() == b"retry"
        assert store.selection("scan") == previous
        selected = store.publish(
            stage,
            "scan",
            IDENTITY,
            expected=previous,
            is_current=lambda: True,
            validate_domain=validate_domain,
        )

    assert store.selection("scan") == selected
    assert read(store) == b"retry"


@pytest.mark.portable
def test_extended_length_store_root_can_publish_and_open_current(
    tmp_path: Path,
) -> None:
    root = tmp_path / "extended-store"
    root.mkdir()
    if sys.platform == "win32":
        root = Path(storage_filesystem._extended_windows_path(root))

    extended_store = ResultStore(root, atomic_rename_supported=True)
    if sys.platform == "win32":
        assert os.fspath(extended_store.root).startswith("\\\\?\\")
    selected = publish(extended_store, b"extended-path")
    assert extended_store.selection("scan") == selected
    assert read(extended_store) == b"extended-path"


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


@pytest.mark.portable
def test_indeterminate_rename_failure_consumes_stage_and_preserves_primary_error(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = publish(store)
    primary_error = OSError(errno.EACCES, "injected directory rename failure")
    destination: list[Path | None] = [None]
    original_lstat = Path.lstat

    def fail_rename(
        _source: str | os.PathLike[str], target: str | os.PathLike[str]
    ) -> None:
        destination[0] = Path(target)
        raise primary_error

    def fail_reconcile_lstat(path: Path) -> os.stat_result:
        if path == destination[0]:
            raise PermissionError(errno.EACCES, "rename outcome is indeterminate")
        return original_lstat(path)

    with store.stage("indeterminate-rename") as stage:
        (stage.path / "payload.bin").write_bytes(b"not-published")
        with monkeypatch.context() as patch:
            patch.setattr(
                "muteinous.infrastructure.storage.bundles.os.rename", fail_rename
            )
            patch.setattr(Path, "lstat", fail_reconcile_lstat)
            with pytest.raises(OSError) as raised:
                store.publish(
                    stage,
                    "scan",
                    IDENTITY,
                    expected=previous,
                    is_current=lambda: True,
                    validate_domain=validate_domain,
                )
        assert raised.value is primary_error
        with pytest.raises(StorageError, match="no longer writable"):
            _ = stage.path
        assert store.selection("scan") == previous
    assert read(store) == b"original"


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
def test_final_expected_selection_recheck_refuses_superseded_publisher(
    store: ResultStore,
) -> None:
    previous = publish(store, b"previous")
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
                    raise TimeoutError("Test did not resume post-rename validation")

        with store.stage("publisher-one") as stage:
            (stage.path / "payload.bin").write_bytes(b"publisher-one")
            return store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=previous,
                is_current=lambda: True,
                validate_domain=slow_validator,
            )

    def publish_second() -> Selection:
        with store.stage("publisher-two") as stage:
            (stage.path / "payload.bin").write_bytes(b"publisher-two")
            return store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=previous,
                is_current=lambda: True,
                validate_domain=validate_domain,
            )

    with ThreadPoolExecutor(max_workers=1) as executor:
        first_future = executor.submit(publish_slowly)
        assert validating.wait(5), "First publisher did not reach committed validation"
        second = publish_second()
        try:
            continue_validation.set()
            with pytest.raises(StorageError, match="superseded"):
                first_future.result(timeout=5)
        finally:
            continue_validation.set()

    assert store.selection("scan") == second
    assert read(store) == b"publisher-two"
    assert (store.root / "bundles" / previous.bundle / "payload.bin").read_bytes() == (
        b"previous"
    )


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
def test_selection_guard_wait_is_bounded_by_configured_timeout(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    timeout = 0.3
    monkeypatch.setattr(storage_bundles, "SELECTION_GUARD_TIMEOUT_SECONDS", timeout)
    acquired = threading.Event()
    release = threading.Event()
    holder_errors: list[BaseException] = []

    def hold_guard() -> None:
        try:
            with try_lock(store.root / "selection.lock") as held:
                if held is None:
                    raise AssertionError("Could not acquire test selection guard")
                acquired.set()
                if not release.wait(3):
                    raise TimeoutError("Test did not release bounded guard holder")
        except BaseException as exc:
            holder_errors.append(exc)

    holder = threading.Thread(target=hold_guard)
    holder.start()
    try:
        assert acquired.wait(5), "Test selection guard was not acquired"
        started = time.monotonic()
        with pytest.raises(StorageError, match="busy"):
            store.selection("scan")
        elapsed = time.monotonic() - started
    finally:
        release.set()
        holder.join(timeout=5)
    assert not holder.is_alive()
    assert not holder_errors
    assert timeout <= elapsed < 2.5


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
    assert read(store) == b"published-after-wait"


@pytest.mark.portable
def test_unreadable_manifest_can_be_regenerated_without_read_fallback(
    store: ResultStore,
) -> None:
    manifest = store.root / "current" / "scan.json"
    manifest.write_bytes(b"not canonical json")

    expected = store.selection("scan")
    assert isinstance(expected, UnreadableSelection)
    with pytest.raises(StorageError, match="unreadable"):
        read(store)

    with store.stage("regenerate-unreadable") as stage:
        (stage.path / "payload.bin").write_bytes(b"regenerated")
        selected = store.publish(
            stage,
            "scan",
            IDENTITY,
            expected=expected,
            is_current=lambda: True,
            validate_domain=validate_domain,
        )

    assert store.selection("scan") == selected
    assert read(store) == b"regenerated"


@pytest.mark.portable
def test_changed_unreadable_manifest_supersedes_captured_marker(
    store: ResultStore,
) -> None:
    manifest = store.root / "current" / "scan.json"
    manifest.write_bytes(b"first corrupt value")
    expected = store.selection("scan")
    assert isinstance(expected, UnreadableSelection)
    manifest.write_bytes(b"different corrupt value")

    with store.stage("stale-unreadable-marker") as stage:
        (stage.path / "payload.bin").write_bytes(b"must not replace")
        with pytest.raises(StorageError, match="superseded"):
            store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=expected,
                is_current=lambda: True,
                validate_domain=validate_domain,
            )

    assert manifest.read_bytes() == b"different corrupt value"
    assert store.selection("scan") == UnreadableSelection(
        hashlib.sha256(b"different corrupt value").hexdigest()
    )


@pytest.mark.portable
def test_nonregular_manifest_is_not_treated_as_unreadable(
    store: ResultStore,
) -> None:
    (store.root / "current" / "scan.json").mkdir()
    with pytest.raises(StorageError, match="Unexpected filesystem entry"):
        store.selection("scan")


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
