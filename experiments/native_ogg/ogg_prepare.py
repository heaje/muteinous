"""Shared-PCM preparation and honest lossy validation for synthetic Vorbis."""

import math
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from experiments.native_ast.ast_core import (
    Decoder,
    Edit,
    Encoder,
    NativeValidationError,
    NativeValidator,
    prepare,
)
from muteinous.core.audio.pcm import PCMFormat
from muteinous.core.audio.wav import WaveStorage

from .ogg_core import OggFormatError, VorbisInfo, parse_ogg_vorbis

RATE = 44_100
CHANNELS = 2
FRAMES = 66_150
INFO = PCMFormat(RATE, CHANNELS, "f32", FRAMES, 3)
GUARD_FRAMES = 2_048
SILENCE_PEAK_LIMIT = 0.0005
MIN_OUTSIDE_SNR_DB = 24.0
MAX_OUTSIDE_ABS_ERROR = 0.08


@dataclass(frozen=True)
class QualityPolicy:
    """Measured decoded-domain tolerances; this is not a transparency claim."""

    guard_frames: int = GUARD_FRAMES
    silence_peak_limit: float = SILENCE_PEAK_LIMIT
    minimum_outside_snr_db: float = MIN_OUTSIDE_SNR_DB
    maximum_outside_abs_error: float = MAX_OUTSIDE_ABS_ERROR

    def __post_init__(self) -> None:
        if (
            self.guard_frames < 0
            or not math.isfinite(self.silence_peak_limit)
            or self.silence_peak_limit < 0
            or not math.isfinite(self.minimum_outside_snr_db)
            or self.minimum_outside_snr_db < 0
            or not math.isfinite(self.maximum_outside_abs_error)
            or self.maximum_outside_abs_error < 0
        ):
            raise ValueError("invalid lossy-validation policy")


@dataclass(frozen=True)
class RegionMetrics:
    start_frame: int
    end_frame: int
    snr_db: float
    maximum_absolute_error: float


@dataclass(frozen=True)
class LossyMetrics:
    edited_region_peaks: tuple[float, ...]
    outside_regions: tuple[RegionMetrics, ...]


def bitrate_is_approximately_preserved(source: int, rebuilt: int) -> bool:
    """Allow modest libvorbis/header rounding, but no silent class change."""
    return (
        source > 0
        and rebuilt > 0
        and abs(source - rebuilt) <= max(16_000, source * 0.15)
    )


def native_validator_for(
    sources: dict[str, VorbisInfo],
) -> NativeValidator:
    """Return the narrow validator that retains each source's comments/profile."""

    def validate(asset_id: str, native: bytes, pcm: bytes, info: PCMFormat) -> None:
        try:
            rebuilt = parse_ogg_vorbis(native, expected_frames=info.frames)
        except OggFormatError as exc:
            raise NativeValidationError(asset_id, str(exc)) from exc
        source = sources.get(asset_id)
        if source is None:
            if rebuilt.nominal_bitrate <= 0:
                raise NativeValidationError(
                    asset_id,
                    "source Vorbis nominal bitrate is absent; re-encoding is refused",
                )
            sources[asset_id] = rebuilt
            source = rebuilt
        if (rebuilt.channels, rebuilt.rate, rebuilt.frames) != (
            info.channels,
            info.rate,
            info.frames,
        ):
            raise NativeValidationError(asset_id, "Vorbis PCM properties changed")
        if len(pcm) != info.frames * info.frame_bytes:
            raise NativeValidationError(asset_id, "decoded PCM frame count mismatch")
        if rebuilt.comment_multiset != source.comment_multiset:
            raise NativeValidationError(asset_id, "Vorbis user comments changed")
        if not bitrate_is_approximately_preserved(
            source.nominal_bitrate, rebuilt.nominal_bitrate
        ):
            raise NativeValidationError(
                asset_id, "Vorbis nominal bitrate class changed"
            )

    return validate


def _outside_regions(
    frames: int, ranges: Sequence[tuple[int, int]], guard: int
) -> list[tuple[int, int]]:
    excluded = sorted(
        (
            max(0, start - guard),
            min(frames, end + guard),
        )
        for start, end in ranges
    )
    merged: list[tuple[int, int]] = []
    for start, end in excluded:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    regions: list[tuple[int, int]] = []
    cursor = 0
    for start, end in merged:
        if cursor < start:
            regions.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < frames:
        regions.append((cursor, frames))
    return regions


def _as_samples(pcm: bytes, info: PCMFormat) -> tuple[float, ...]:
    if info.representation != "f32" or len(pcm) != info.frames * info.frame_bytes:
        raise ValueError("decoded Vorbis PCM has invalid float frame count")
    samples = tuple(value[0] for value in struct.iter_unpack("<f", pcm))
    if any(not math.isfinite(sample) for sample in samples):
        raise ValueError("decoded Vorbis PCM contains a non-finite sample")
    return samples


def measure_lossy_effects(
    original: bytes,
    decoded: bytes,
    ranges: Sequence[tuple[int, int]],
    info: PCMFormat,
    *,
    policy: QualityPolicy = QualityPolicy(),
) -> LossyMetrics:
    """Measure decoded output without implying losslessness or transparency."""
    original_samples = _as_samples(original, info)
    decoded_samples = _as_samples(decoded, info)
    if len(decoded_samples) != info.frames * info.channels:
        raise ValueError("rebuilt Vorbis frame count changed")

    mute_peaks: list[float] = []
    for start, end in ranges:
        mute_start = start + policy.guard_frames
        mute_end = end - policy.guard_frames
        if mute_start >= mute_end:
            raise ValueError("required edit is too short for the Vorbis guard region")
        sample_start = mute_start * info.channels
        sample_end = mute_end * info.channels
        mute_peaks.append(
            max(abs(value) for value in decoded_samples[sample_start:sample_end])
        )

    regions: list[RegionMetrics] = []
    for start, end in _outside_regions(info.frames, ranges, policy.guard_frames):
        sample_start = start * info.channels
        sample_end = end * info.channels
        source = original_samples[sample_start:sample_end]
        output = decoded_samples[sample_start:sample_end]
        if not source:
            continue
        error = [actual - expected for expected, actual in zip(source, output)]
        peak_error = max(abs(value) for value in error)
        signal_energy = math.fsum(value * value for value in source)
        error_energy = math.fsum(value * value for value in error)
        snr = (
            math.inf
            if error_energy == 0
            else (
                -math.inf
                if signal_energy == 0
                else 10.0 * math.log10(signal_energy / error_energy)
            )
        )
        regions.append(RegionMetrics(start, end, snr, peak_error))
    return LossyMetrics(tuple(mute_peaks), tuple(regions))


def verify_lossy_reconstruction(
    asset_id: str,
    original: bytes,
    edited: bytes,
    decoded: bytes,
    ranges: Sequence[tuple[int, int]],
    info: PCMFormat,
    *,
    policy: QualityPolicy = QualityPolicy(),
) -> None:
    """Check exact frame count, edited silence, and unchanged-region quality."""
    del asset_id
    _as_samples(edited, info)
    measured = measure_lossy_effects(original, decoded, ranges, info, policy=policy)
    for peak in measured.edited_region_peaks:
        if peak > policy.silence_peak_limit:
            raise ValueError(
                f"edited-region peak {peak:.8f} exceeds {policy.silence_peak_limit:.8f}"
            )
    for region_index, region in enumerate(measured.outside_regions):
        if region.maximum_absolute_error > policy.maximum_outside_abs_error:
            raise ValueError(
                f"unaffected-region {region_index} peak error "
                f"{region.maximum_absolute_error:.8f} "
                f"exceeds {policy.maximum_outside_abs_error:.8f}"
            )
        if region.snr_db < policy.minimum_outside_snr_db:
            raise ValueError(
                f"unaffected-region {region_index} SNR {region.snr_db:.2f} dB is below "
                f"{policy.minimum_outside_snr_db:.2f} dB"
            )


def prepare_ogg(
    root: Path,
    assets: Mapping[str, bytes],
    originals: Mapping[str, bytes],
    edits: Sequence[Edit],
    *,
    decoder: Decoder,
    encoder: Encoder,
    info: PCMFormat = INFO,
    storage: WaveStorage | None = None,
    quality: QualityPolicy = QualityPolicy(),
) -> dict[str, bytes]:
    """Parse each source, then reuse AST's private all-or-nothing PCM workflow."""
    sources: dict[str, VorbisInfo] = {}
    return prepare(
        root,
        assets,
        originals,
        edits,
        decoder=decoder,
        encoder=encoder,
        storage=storage,
        info=info,
        native_extension=".ogg",
        native_validator=native_validator_for(sources),
        reconstruction_verifier=lambda asset_id, original, edited, decoded, ranges, pcm_info: (
            verify_lossy_reconstruction(
                asset_id,
                original,
                edited,
                decoded,
                ranges,
                pcm_info,
                policy=quality,
            )
        ),
    )
