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
    group_edits,
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
EDIT_PADDING_FRAMES = 224
SILENCE_PEAK_LIMIT = 0.0005
MIN_OUTSIDE_SNR_DB = 24.0
MAX_OUTSIDE_ABS_ERROR = 0.08
MIN_GUARD_SNR_DB = 18.0
MAX_GUARD_ABS_ERROR = 0.05


@dataclass(frozen=True)
class QualityPolicy:
    """Measured decoded-domain tolerances; this is not a transparency claim."""

    guard_frames: int = GUARD_FRAMES
    padding_frames: int = EDIT_PADDING_FRAMES
    silence_peak_limit: float = SILENCE_PEAK_LIMIT
    minimum_outside_snr_db: float = MIN_OUTSIDE_SNR_DB
    maximum_outside_abs_error: float = MAX_OUTSIDE_ABS_ERROR
    minimum_guard_snr_db: float = MIN_GUARD_SNR_DB
    maximum_guard_abs_error: float = MAX_GUARD_ABS_ERROR

    def __post_init__(self) -> None:
        if (
            self.guard_frames < 0
            or self.padding_frames < 0
            or not math.isfinite(self.silence_peak_limit)
            or self.silence_peak_limit < 0
            or not math.isfinite(self.minimum_outside_snr_db)
            or self.minimum_outside_snr_db < 0
            or not math.isfinite(self.maximum_outside_abs_error)
            or self.maximum_outside_abs_error < 0
            or not math.isfinite(self.minimum_guard_snr_db)
            or self.minimum_guard_snr_db < 0
            or not math.isfinite(self.maximum_guard_abs_error)
            or self.maximum_guard_abs_error < 0
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
    guard_regions: tuple[RegionMetrics, ...]


def bitrate_is_approximately_preserved(source: int, rebuilt: int) -> bool:
    """Allow at most ten-percent nominal header rounding; reject class changes."""
    return source > 0 and rebuilt > 0 and abs(source - rebuilt) <= source * 0.10


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


def _merge_ranges(ranges: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            prior_start, prior_end = merged[-1]
            merged[-1] = (prior_start, max(prior_end, end))
        else:
            merged.append((start, end))
    return merged


def _padded_ranges(
    ranges: Sequence[tuple[int, int]], frames: int, padding: int
) -> list[tuple[int, int]]:
    """Widen edits in integer frames, clamp to the clip, and merge touching spans."""
    if frames <= 0 or padding < 0:
        raise ValueError("invalid Ogg edit padding bounds")
    _validate_ranges(ranges, frames)
    return _merge_ranges(
        [(max(0, start - padding), min(frames, end + padding)) for start, end in ranges]
    )


def _validate_ranges(ranges: Sequence[tuple[int, int]], frames: int) -> None:
    if frames <= 0 or any(
        type(start) is not int or type(end) is not int or not 0 <= start < end <= frames
        for start, end in ranges
    ):
        raise ValueError("invalid edit frame range")


def _subtract_ranges(
    regions: Sequence[tuple[int, int]], exclusions: Sequence[tuple[int, int]]
) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    for start, end in regions:
        cursor = start
        for excluded_start, excluded_end in exclusions:
            if excluded_end <= cursor:
                continue
            if excluded_start >= end:
                break
            if cursor < excluded_start:
                result.append((cursor, min(end, excluded_start)))
            cursor = max(cursor, excluded_end)
            if cursor >= end:
                break
        if cursor < end:
            result.append((cursor, end))
    return result


def _guard_regions(
    frames: int, ranges: Sequence[tuple[int, int]], guard: int
) -> list[tuple[int, int]]:
    """Return unedited frames within one guard width of either edit edge."""
    edits = _merge_ranges(ranges)
    windows = _merge_ranges(
        [(max(0, start - guard), start) for start, _ in edits if guard and start > 0]
        + [
            (end, min(frames, end + guard))
            for _, end in edits
            if guard and end < frames
        ]
    )
    return _subtract_ranges(windows, edits)


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
    requested_ranges: Sequence[tuple[int, int]] | None = None,
) -> LossyMetrics:
    """Measure decoded output without implying losslessness or transparency."""
    original_samples = _as_samples(original, info)
    decoded_samples = _as_samples(decoded, info)
    if len(decoded_samples) != info.frames * info.channels:
        raise ValueError("rebuilt Vorbis frame count changed")
    _validate_ranges(ranges, info.frames)
    silence_ranges = ranges if requested_ranges is None else requested_ranges
    _validate_ranges(silence_ranges, info.frames)

    mute_peaks: list[float] = []
    for start, end in silence_ranges:
        sample_start = start * info.channels
        sample_end = end * info.channels
        mute_peaks.append(
            max(abs(value) for value in decoded_samples[sample_start:sample_end])
        )

    def measure(regions: Sequence[tuple[int, int]]) -> list[RegionMetrics]:
        measured: list[RegionMetrics] = []
        for start, end in regions:
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
            measured.append(RegionMetrics(start, end, snr, peak_error))
        return measured

    outside = measure(_outside_regions(info.frames, ranges, policy.guard_frames))
    guards = measure(_guard_regions(info.frames, ranges, policy.guard_frames))
    return LossyMetrics(tuple(mute_peaks), tuple(outside), tuple(guards))


def _edit_covers_entire_clip(frames: int, ranges: Sequence[tuple[int, int]]) -> bool:
    return _merge_ranges(ranges) == [(0, frames)]


def verify_lossy_reconstruction(
    asset_id: str,
    original: bytes,
    edited: bytes,
    decoded: bytes,
    ranges: Sequence[tuple[int, int]],
    info: PCMFormat,
    *,
    policy: QualityPolicy = QualityPolicy(),
    requested_ranges: Sequence[tuple[int, int]] | None = None,
) -> None:
    """Check exact frame count, edited silence, and bounded fidelity everywhere else."""
    del asset_id
    _as_samples(edited, info)
    _validate_ranges(ranges, info.frames)
    silence_ranges = ranges if requested_ranges is None else requested_ranges
    _validate_ranges(silence_ranges, info.frames)
    measured = measure_lossy_effects(
        original,
        decoded,
        ranges,
        info,
        policy=policy,
        requested_ranges=silence_ranges,
    )
    for peak in measured.edited_region_peaks:
        if peak > policy.silence_peak_limit:
            raise ValueError(
                f"requested-range silence peak {peak:.8f} exceeds "
                f"{policy.silence_peak_limit:.8f}"
            )
    verified_unedited_frames = sum(
        region.end_frame - region.start_frame
        for region in (*measured.outside_regions, *measured.guard_regions)
    )
    if verified_unedited_frames == 0 and not _edit_covers_entire_clip(
        info.frames, silence_ranges
    ):
        raise ValueError("no unedited frames were verified")
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
    for region_index, region in enumerate(measured.guard_regions):
        if region.maximum_absolute_error > policy.maximum_guard_abs_error:
            raise ValueError(
                f"unaffected guard-region {region_index} peak error "
                f"{region.maximum_absolute_error:.8f} "
                f"exceeds {policy.maximum_guard_abs_error:.8f}"
            )
        if region.snr_db < policy.minimum_guard_snr_db:
            raise ValueError(
                f"unaffected guard-region {region_index} SNR {region.snr_db:.2f} dB "
                f"is below {policy.minimum_guard_snr_db:.2f} dB"
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
    requested_ranges = group_edits(assets, edits, total_frames=info.frames)
    padded_ranges = {
        asset_id: _padded_ranges(ranges, info.frames, quality.padding_frames)
        for asset_id, ranges in requested_ranges.items()
    }
    padded_edits = tuple(
        Edit(asset_id, 0, info.frames, start, end)
        for asset_id, ranges in padded_ranges.items()
        for start, end in ranges
    )

    def verify(
        asset_id: str,
        original: bytes,
        edited: bytes,
        decoded: bytes,
        ranges: Sequence[tuple[int, int]],
        pcm_info: PCMFormat,
    ) -> None:
        verify_lossy_reconstruction(
            asset_id,
            original,
            edited,
            decoded,
            ranges,
            pcm_info,
            policy=quality,
            requested_ranges=requested_ranges[asset_id],
        )

    return prepare(
        root,
        assets,
        originals,
        padded_edits,
        decoder=decoder,
        encoder=encoder,
        storage=storage,
        info=info,
        native_extension=".ogg",
        native_validator=native_validator_for(sources),
        reconstruction_verifier=verify,
    )
