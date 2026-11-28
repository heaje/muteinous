"""Scheduled hashing with known synthetic originals and dependency evidence."""

import os
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import cast

import pytest

from muteinous.infrastructure.jobs.queue import JobQueue, JobState
from muteinous.infrastructure.sources import scheduled
from muteinous.infrastructure.sources.fingerprints import (
    UnstableSourceError,
    fingerprint_assets,
)
from muteinous.infrastructure.sources.scheduled import (
    OriginalCheck,
    SourceVerification,
    submit_source_verification,
    validate_source_plan,
)
from muteinous.models.source import SegmentAssets, SourceAssetId, SourceFingerprint
from tests.support.job_queue import eventually

pytestmark = pytest.mark.portable


def known_original(provider: str, source_id: str, root: Path) -> str | None:
    if provider == "synthetic" and source_id == "originals" and root.is_dir():
        return None
    return "Original source is unknown or replaced"


def make_queue(check: OriginalCheck = known_original) -> JobQueue:
    return JobQueue(
        {"cpu": 1, "source-io": 1},
        lambda plan: validate_source_plan(plan, check),
    )


def submit(
    queue: JobQueue,
    root: Path,
    paths: dict[SourceAssetId, Path],
    previous: dict[SourceAssetId, SourceFingerprint],
    dependencies: SegmentAssets,
    *,
    current: SegmentAssets | None = None,
    check: OriginalCheck = known_original,
    source_id: str = "originals",
) -> str:
    return submit_source_verification(
        queue,
        provider="synthetic",
        source_id=source_id,
        root=root,
        paths=paths,
        results={segment: segment for segment in dependencies},
        previous_dependencies=dependencies,
        current_dependencies=dependencies if current is None else current,
        previous_fingerprints=previous,
        check_original=check,
    )


def test_scheduled_verification_preserves_only_positive_evidence(
    tmp_path: Path,
) -> None:
    changed, missing, stable = map(SourceAssetId, ("changed", "missing", "stable"))
    paths = {asset: tmp_path / asset for asset in (changed, missing, stable)}
    for path in paths.values():
        path.write_bytes(b"original")
    previous = fingerprint_assets(paths)
    metadata = paths[changed].stat()
    paths[changed].write_bytes(b"modified")
    os.utime(paths[changed], ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    paths[missing].unlink()
    dependencies = {
        "changed": frozenset({changed}),
        "missing": frozenset({missing}),
        "stable": frozenset({stable}),
        "shared": frozenset({stable, missing}),
        "reassociated": frozenset({stable}),
    }
    current = dependencies | {"reassociated": frozenset({changed})}
    queue = make_queue()
    try:
        job = submit(queue, tmp_path, paths, previous, dependencies, current=current)
        assert queue.drain(5)
        snapshot = queue.snapshot(job)
        assert snapshot.state == JobState.COMPLETED, snapshot.detail
        result = cast(SourceVerification[str], snapshot.result)
        assert result.validity.retained == {"stable": "stable"}
        assert result.validity.invalidated == frozenset(
            {"changed", "missing", "shared", "reassociated"}
        )
        assert set(result.failures) == {missing}
        assert result.fingerprints[changed] != previous[changed]
        assert snapshot.progress.overall_count is not None
        assert snapshot.progress.overall_count.percentage == 100
        assert snapshot.progress.stage_count is not None
        assert snapshot.progress.stage_count.percentage is None
        assert paths[stable].read_bytes() == b"original"
        assert paths[changed].read_bytes() == b"modified"

        broad = submit(queue, tmp_path, paths, previous, dependencies, current={})
        assert queue.drain(5)
        result = cast(SourceVerification[str], queue.snapshot(broad).result)
        assert result.validity.invalidated == frozenset(dependencies)
        assert not result.validity.retained
    finally:
        queue.close()


@pytest.mark.parametrize("reason", ["Known replacement", "Ambiguous provenance"])
def test_original_refusal_before_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    asset = SourceAssetId("asset")
    path = tmp_path / "asset"
    path.write_bytes(b"original")

    def refuse(provider: str, source_id: str, root: Path) -> str:
        return reason

    def forbidden(*args: object, **kwargs: object) -> SourceFingerprint:
        pytest.fail("An ineligible plan must not hash")

    monkeypatch.setattr(scheduled, "fingerprint_file", forbidden)
    queue = make_queue(refuse)
    try:
        job = submit(queue, tmp_path, {asset: path}, {}, {}, check=refuse)
        assert queue.drain(5)
        snapshot = queue.snapshot(job)
        assert snapshot.state == JobState.NEEDS_ATTENTION
        assert snapshot.detail == reason
        assert snapshot.result is None
    finally:
        queue.close()


def test_cancellation_holds_both_resources_until_physical_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = SourceAssetId("asset")
    path = tmp_path / "asset"
    path.write_bytes(b"x" * (1024 * 1024))
    previous = fingerprint_assets({asset: path})
    dependencies = {"segment": frozenset({asset})}
    entered, release = Event(), Event()
    original = scheduled.fingerprint_file

    def blocked(
        path: Path,
        *,
        cancelled: Callable[[], bool] | None = None,
        report_bytes: Callable[[int], None] | None = None,
    ) -> SourceFingerprint:
        def report(count: int) -> None:
            if report_bytes is not None:
                report_bytes(count)
            entered.set()
            assert release.wait(5)

        return original(path, cancelled=cancelled, report_bytes=report)

    monkeypatch.setattr(scheduled, "fingerprint_file", blocked)
    queue = make_queue()
    try:
        running = submit(queue, tmp_path, {asset: path}, previous, dependencies)
        assert entered.wait(5)
        waiting = submit(queue, tmp_path, {asset: path}, previous, dependencies)
        eventually(lambda: "Waiting for:" in (queue.snapshot(waiting).detail or ""))
        detail = queue.snapshot(waiting).detail or ""
        assert "cpu" in detail and "source-io" in detail
        assert queue.cancel(waiting)
        assert queue.cancel(running)
        assert queue.snapshot(running).physical_running
        next_job = submit(queue, tmp_path, {asset: path}, previous, dependencies)
        eventually(lambda: "Waiting for:" in (queue.snapshot(next_job).detail or ""))
        assert queue.snapshot(next_job).state == JobState.QUEUED
        release.set()
        assert queue.drain(5)
        for job in (waiting, running):
            snapshot = queue.snapshot(job)
            assert snapshot.state == JobState.CANCELLED
            assert not snapshot.physical_running
            assert snapshot.result is None
        assert queue.snapshot(next_job).state == JobState.COMPLETED
    finally:
        release.set()
        queue.close()


def test_unexpected_error_fails_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> SourceFingerprint:
        raise RuntimeError("unexpected defect")

    monkeypatch.setattr(scheduled, "fingerprint_file", broken)
    queue = make_queue()
    try:
        job = submit(
            queue, tmp_path, {SourceAssetId("asset"): tmp_path / "asset"}, {}, {}
        )
        assert queue.drain(5)
        snapshot = queue.snapshot(job)
        assert snapshot.state == JobState.FAILED
        assert snapshot.result is None
        assert "unexpected defect" in (snapshot.detail or "")
    finally:
        queue.close()


@pytest.mark.parametrize("failure", [PermissionError, UnstableSourceError])
def test_attributable_failure_preserves_independent_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: type[OSError],
) -> None:
    failed, stable = map(SourceAssetId, ("failed", "stable"))
    paths = {asset: tmp_path / asset for asset in (failed, stable)}
    for path in paths.values():
        path.write_bytes(b"original")
    previous = fingerprint_assets(paths)
    dependencies = {
        "failed": frozenset({failed}),
        "stable": frozenset({stable}),
    }
    original = scheduled.fingerprint_file

    def controlled(
        path: Path,
        *,
        cancelled: Callable[[], bool] | None = None,
        report_bytes: Callable[[int], None] | None = None,
    ) -> SourceFingerprint:
        if path == paths[failed]:
            raise failure("controlled asset failure")
        return original(path, cancelled=cancelled, report_bytes=report_bytes)

    monkeypatch.setattr(scheduled, "fingerprint_file", controlled)
    queue = make_queue()
    try:
        job = submit(queue, tmp_path, paths, previous, dependencies)
        assert queue.drain(5)
        snapshot = queue.snapshot(job)
        assert snapshot.state == JobState.COMPLETED, snapshot.detail
        result = cast(SourceVerification[str], snapshot.result)
        assert result.validity.retained == {"stable": "stable"}
        assert result.validity.invalidated == frozenset({"failed"})
        assert failure.__name__ in result.failures[failed]
        assert failed not in result.fingerprints
    finally:
        queue.close()


def test_unavailable_context_after_hash_rejects_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset = SourceAssetId("asset")
    path = tmp_path / "asset"
    path.write_bytes(b"original")
    previous = fingerprint_assets({asset: path})
    dependencies = {"segment": frozenset({asset})}
    unavailable = Event()
    original = scheduled.fingerprint_file

    def check(provider: str, source_id: str, root: Path) -> str | None:
        if unavailable.is_set():
            return "Original context became unavailable"
        return known_original(provider, source_id, root)

    def verify(
        path: Path,
        *,
        cancelled: Callable[[], bool] | None = None,
        report_bytes: Callable[[int], None] | None = None,
    ) -> SourceFingerprint:
        result = original(path, cancelled=cancelled, report_bytes=report_bytes)
        unavailable.set()
        return result

    monkeypatch.setattr(scheduled, "fingerprint_file", verify)
    queue = make_queue(check)
    try:
        job = submit(
            queue, tmp_path, {asset: path}, previous, dependencies, check=check
        )
        assert queue.drain(5)
        snapshot = queue.snapshot(job)
        assert snapshot.state == JobState.FAILED
        assert snapshot.result is None
        assert "Original context became unavailable" in (snapshot.detail or "")
    finally:
        queue.close()
