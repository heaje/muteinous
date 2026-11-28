"""Deterministic, bounded-memory content fingerprints."""

import os
import stat
from collections.abc import Callable, Mapping
from pathlib import Path

from blake3 import blake3

from muteinous.models.source import SourceAssetId, SourceFingerprint

# A reused 256 KiB buffer bounds memory per call; see the read-size sweep.
_HASH_CHUNK_SIZE = 256 * 1024


class UnstableSourceError(OSError):
    """The file changed or was replaced during fingerprinting."""


class FingerprintCancelled(RuntimeError):
    """No complete fingerprint may be returned from cancelled work."""


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise FingerprintCancelled("Source fingerprinting cancelled")


def _check_stable(before: os.stat_result, after: os.stat_result) -> None:
    if (
        not stat.S_ISREG(after.st_mode)
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or (before.st_ino and after.st_ino and not os.path.samestat(before, after))
    ):
        raise UnstableSourceError("Source changed during fingerprinting")


def new_fingerprint_buffer() -> bytearray:
    """Allocate a fixed-size read buffer for one sequential hashing worker."""
    return bytearray(_HASH_CHUNK_SIZE)


def fingerprint_file(
    path: Path,
    *,
    buffer: bytearray | None = None,
    cancelled: Callable[[], bool] | None = None,
    report_bytes: Callable[[int], None] | None = None,
) -> SourceFingerprint:
    """Fingerprint a plugin-selected content boundary without loading it whole.

    The caller establishes original-source provenance. Stability checks reject
    detectable concurrent changes, not every possible check/open race. Progress
    reports cumulative bytes read; cancellation is cooperative between reads.
    A supplied buffer belongs exclusively to this sequential caller and can
    be reused for subsequent assets; hash state is always new for each file.
    """
    _check_cancelled(cancelled)
    initial = path.stat()
    if not stat.S_ISREG(initial.st_mode):
        raise OSError("Source is not a regular file")
    hasher = blake3(max_threads=1)
    if buffer is None:
        buffer = new_fingerprint_buffer()
    if len(buffer) != _HASH_CHUNK_SIZE:
        raise ValueError("Fingerprint buffer must be 256 KiB")
    view = memoryview(buffer)
    completed = 0
    with path.open("rb", buffering=0) as source:
        before = os.fstat(source.fileno())
        _check_stable(initial, before)
        while True:
            _check_cancelled(cancelled)
            count = source.readinto(buffer)
            _check_cancelled(cancelled)
            if not count:
                break
            hasher.update(view[:count])
            completed += count
            if report_bytes is not None:
                report_bytes(completed)
        _check_stable(before, os.fstat(source.fileno()))
        if completed != before.st_size:
            raise UnstableSourceError("Source size differs from bytes read")
    _check_stable(before, path.stat())
    _check_cancelled(cancelled)
    return SourceFingerprint(f"blake3:{hasher.hexdigest()}")


def fingerprint_assets(
    paths: Mapping[SourceAssetId, Path],
) -> dict[SourceAssetId, SourceFingerprint]:
    """Fingerprint plugin-defined assets sequentially; errors reject the batch."""
    buffer = new_fingerprint_buffer()
    return {
        asset_id: fingerprint_file(path, buffer=buffer)
        for asset_id, path in paths.items()
    }
