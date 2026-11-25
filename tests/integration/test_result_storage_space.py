"""Result-storage integration tests for real filesystem boundaries."""

from __future__ import annotations

import errno
from pathlib import Path
from types import SimpleNamespace
from typing import Never

import pytest

from muteinous.infrastructure.storage._filesystem import (
    InsufficientSpace,
    StorageError,
    checked_directory,
    checked_stat,
)
from muteinous.infrastructure.storage.bundles import ResultStore
from muteinous.infrastructure.storage.space import SpaceRequirement, preflight
from tests.support.storage import IDENTITY, publish, read, validate_domain


@pytest.mark.portable
def test_default_stage_minimum_is_zero_when_no_space_is_free(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "muteinous.infrastructure.storage.space.shutil.disk_usage",
        lambda path: SimpleNamespace(free=0),
    )

    with store.stage("zero-free-space-default") as stage:
        assessment = stage.space_assessments[0]
        assert assessment.minimum == 0
        assert assessment.available == 0
        assert stage.path.is_dir()


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

    def record_rename(*args: object) -> None:
        rename_calls.append(args)

    monkeypatch.setattr(
        "muteinous.infrastructure.storage.bundles.os.rename", record_rename
    )
    with store.stage("different-device") as stage:
        (stage.path / "payload.bin").write_bytes(b"candidate")
        monkeypatch.setattr(
            "muteinous.infrastructure.storage.bundles.checked_directory",
            different_current_device,
        )
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
@pytest.mark.parametrize("mismatched_directory", ["current", "stage-leases"])
def test_stage_refuses_mismatched_destination_devices_before_creation(
    store: ResultStore,
    monkeypatch: pytest.MonkeyPatch,
    mismatched_directory: str,
) -> None:
    staging = store.root / "staging"
    leases = store.root / "stage-leases"
    staging_before = set(staging.iterdir())
    leases_before = set(leases.iterdir())
    original_checked_directory = checked_directory

    def different_directory_device(path: Path, *, root: Path | None = None) -> object:
        info = original_checked_directory(path, root=root)
        if path == store.root / mismatched_directory:
            return SimpleNamespace(st_dev=info.st_dev + 1)
        return info

    def unexpected_preflight(*args: object, **kwargs: object) -> Never:
        raise AssertionError("Stage device validation must precede preflight")

    monkeypatch.setattr(
        "muteinous.infrastructure.storage.bundles.checked_directory",
        different_directory_device,
    )
    monkeypatch.setattr(
        "muteinous.infrastructure.storage.bundles.preflight", unexpected_preflight
    )
    with pytest.raises(StorageError, match="destination-filesystem staging"):
        with store.stage(f"mismatched-{mismatched_directory}-device"):
            pytest.fail("A stage was yielded on a mismatched destination device")

    assert set(staging.iterdir()) == staging_before
    assert set(leases.iterdir()) == leases_before
