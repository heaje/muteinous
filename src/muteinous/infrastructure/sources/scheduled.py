"""Scheduled verification of caller-established original source assets."""

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from muteinous.infrastructure.jobs.queue import (
    JobContext,
    JobPlan,
    JobQueue,
    Progress,
    WorkCount,
)
from muteinous.infrastructure.sources.fingerprints import (
    FingerprintCancelled,
    fingerprint_file,
    new_fingerprint_buffer,
)
from muteinous.infrastructure.sources.validity import (
    SourceValidity,
    compare_source_evidence,
)
from muteinous.models.source import (
    AssetFingerprints,
    SegmentAssets,
    SourceAssetId,
    SourceFingerprint,
)

_Result = TypeVar("_Result")
SOURCE_RESOURCES = ("cpu", "source-io")
SOURCE_BACKEND = "blake3"
DEFAULT_SOURCE_IO_CAPACITY = 2
# A caller-owned, read-only check of the resolved original-source context.
# None means known originals; a reason means unavailable, replaced or ambiguous.
OriginalCheck = Callable[[str, str, Path], str | None]


def source_verification_capacities(capacities: Mapping[str, int]) -> dict[str, int]:
    """Supply the source-I/O default when configuring the shared queue.

    Explicit capacities, including zero (unavailable), take precedence.
    CPU and other resource capacities remain the queue owner's responsibility.
    """
    return {"source-io": DEFAULT_SOURCE_IO_CAPACITY, **capacities}


@dataclass(frozen=True, slots=True)
class SourceVerification(Generic[_Result]):
    validity: SourceValidity[_Result]
    fingerprints: AssetFingerprints
    failures: Mapping[SourceAssetId, str]


def validate_source_plan(plan: JobPlan, check_original: OriginalCheck) -> str | None:
    """Check resolved source context, not individual asset metadata or content.

    Route source-verification plans here from the shared queue's validator.
    The caller's check must establish current eligibility without hashing or
    enumeration. Queue capacity checks remain the queue's responsibility.
    """
    if plan.backend != SOURCE_BACKEND or plan.resources != SOURCE_RESOURCES:
        return "Source verification execution context is unavailable"
    data = json.loads(plan.input_json)
    source_id = data.get("source_id")
    root = data.get("root")
    if not isinstance(source_id, str) or not source_id or not isinstance(root, str):
        return "Source verification context is invalid"
    path = Path(root)
    if not path.is_absolute() or not path.is_dir():
        return "Original source location is unavailable"
    return check_original(plan.provider, source_id, path)


def submit_source_verification(
    queue: JobQueue,
    *,
    provider: str,
    source_id: str,
    root: Path,
    paths: Mapping[SourceAssetId, Path],
    results: Mapping[str, _Result],
    previous_dependencies: SegmentAssets,
    current_dependencies: SegmentAssets,
    previous_fingerprints: AssetFingerprints,
    check_original: OriginalCheck,
) -> str:
    """Submit one sequential verification job using the shared queue.

    The caller supplies a resolved original-source context and the complete
    plugin-owned asset associations. The check must attest the actual source
    selection, not infer provenance from a path or a matching digest. The
    queue owner configures shared capacities with source_verification_capacities
    and routes dispatch validation through validate_source_plan with the same
    check. No original/backup discovery is performed here.
    """
    plan = JobPlan(
        provider,
        SOURCE_BACKEND,
        SOURCE_RESOURCES,
        json.dumps({"source_id": source_id, "root": str(root.absolute())}),
    )
    # Freeze the in-process input selection before dispatch; result values
    # themselves are caller-owned and must not be mutated during execution.
    selected = {asset: path.absolute() for asset, path in paths.items()}
    prior = dict(results)
    old_dependencies = dict(previous_dependencies)
    new_dependencies = dict(current_dependencies)
    old_fingerprints = dict(previous_fingerprints)

    def run(submitted: JobPlan, context: JobContext) -> SourceVerification[_Result]:
        reason = validate_source_plan(submitted, check_original)
        if reason is not None:
            raise ValueError(reason)
        fingerprints: dict[SourceAssetId, SourceFingerprint] = {}
        failures: dict[SourceAssetId, str] = {}
        total = len(selected)
        buffer = new_fingerprint_buffer()
        for index, (asset, path) in enumerate(selected.items()):
            if context.cancelled:
                raise FingerprintCancelled("Source verification cancelled")
            last_report = time.monotonic()
            bytes_read = 0

            def report(count: int) -> None:
                nonlocal last_report, bytes_read
                bytes_read = count
                now = time.monotonic()
                if now - last_report >= 0.25:
                    context.report(
                        Progress(
                            stage="Verifying sources",
                            activity=str(asset),
                            stage_count=WorkCount(count),
                            overall_count=WorkCount(index, total, reliable=True),
                        ),
                        meaningful=True,
                    )
                    last_report = now

            context.report(
                Progress(
                    stage="Verifying sources",
                    activity=str(asset),
                    stage_count=WorkCount(0),
                    overall_count=WorkCount(index, total, reliable=True),
                )
            )
            try:
                fingerprints[asset] = fingerprint_file(
                    path,
                    buffer=buffer,
                    cancelled=lambda: context.cancelled,
                    report_bytes=report,
                )
            except OSError as error:
                failures[asset] = f"{type(error).__name__}: {error}"
            context.report(
                Progress(
                    stage="Verifying sources",
                    activity=str(asset),
                    stage_count=WorkCount(bytes_read),
                    overall_count=WorkCount(index + 1, total, reliable=True),
                ),
                meaningful=True,
            )
        if context.cancelled:
            raise FingerprintCancelled("Source verification cancelled")
        reason = validate_source_plan(submitted, check_original)
        if reason is not None:
            raise ValueError(reason)
        return SourceVerification(
            compare_source_evidence(
                prior,
                old_dependencies,
                new_dependencies,
                old_fingerprints,
                fingerprints,
            ),
            fingerprints,
            failures,
        )

    return queue.submit(plan, run)
