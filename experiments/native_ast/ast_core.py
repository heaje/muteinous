"""Pure-Python AST fixture logic and all-or-nothing shared-PCM preparation.

This deliberately supports one synthetic AST profile only. Native tools enter
through the decoder and encoder callables so required tests need no FFmpeg.
"""

import math
import struct
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from muteinous.core.audio.pcm import BLOCK_FRAMES, PCMFormat
from muteinous.core.audio.scratch import audio_scratch
from muteinous.core.audio.wav import WaveStorage

RATE = 32_000
FRAMES = 8_192
CHANNELS = 2
LOOP_START = 1_024
LOOP_END = 6_144
AST_PACKET_FRAMES = 2_048
INFO = PCMFormat(RATE, CHANNELS, "s16", FRAMES, 3)

Boundary = Literal["start", "end"]
Decoder = Callable[[str, Path, Path, PCMFormat], None]
Encoder = Callable[[str, Path, Path, PCMFormat], None]
NativeValidator = Callable[[str, bytes, bytes, PCMFormat], None]
ReconstructionVerifier = Callable[
    [str, bytes, bytes, bytes, Sequence[tuple[int, int]], PCMFormat], None
]


class NativeStageError(ValueError):
    """A required native-asset stage failed; always identifies its asset."""

    stage = "preparation"

    def __init__(self, asset_id: str, detail: str) -> None:
        self.asset_id = asset_id
        self.detail = detail
        super().__init__(f"required asset {asset_id}: {self.stage}: {detail}")


class NativeValidationError(NativeStageError):
    stage = "native validation"


class ExtractionError(NativeStageError):
    stage = "extraction"


class EditError(NativeStageError):
    stage = "PCM edit"


class ReconstructionError(NativeStageError):
    stage = "reconstruction"


@dataclass(frozen=True)
class Edit:
    asset: str
    segment_start: int
    segment_frames: int
    start: int
    end: int


@dataclass(frozen=True)
class ParsedAST:
    codec: int
    bits: int
    channels: int
    loop_flag: int
    rate: int
    frames: int
    loop_start: int
    loop_end: int
    first_block_size: int
    header_extension: bytes
    block_widths: tuple[int, ...]
    pcm: bytes


def _canonical_block_widths(frames: int) -> tuple[int, ...]:
    """AST BLCK widths in bytes per channel for observed FFmpeg PCM packets.

    FFmpeg's AST muxer writes one BLCK for each encoded PCM packet. The
    pcm_s16be_planar path emits 2048-frame packets for this fixture profile;
    each channel plane is therefore 4096 bytes, except the final short packet.
    """
    if frames <= 0:
        return ()
    widths: list[int] = []
    remaining = frames
    while remaining:
        packet_frames = min(AST_PACKET_FRAMES, remaining)
        widths.append(packet_frames * 2)
        remaining -= packet_frames
    return tuple(widths)


def build_canonical_ast(
    pcm: bytes,
    info: PCMFormat = INFO,
    *,
    loop_start: int = LOOP_START,
    loop_end: int = LOOP_END,
) -> bytes:
    """Write the one supported canonical AST profile from interleaved s16le."""
    if (
        info.rate <= 0
        or info.channels != CHANNELS
        or info.representation != "s16"
        or info.channel_mask != 3
        or info.frames <= 0
        or len(pcm) != info.frames * info.frame_bytes
    ):
        raise ValueError("fixture requires complete stereo s16 PCM with WAVE mask 3")
    if not 0 <= loop_start < loop_end <= info.frames:
        raise ValueError("invalid fixture loop bounds")

    widths = _canonical_block_widths(info.frames)
    body_size = sum(32 + 2 * width for width in widths)
    output = bytearray(
        struct.pack(
            ">4sI4H5I",
            b"STRM",
            body_size,
            1,  # PCM16 codec
            16,
            CHANNELS,
            0xFFFF,
            info.rate,
            info.frames,
            loop_start,
            loop_end,
            widths[0],
        )
    )
    # astenc.c writes four zero bytes, a little-endian 0x7f unknown marker,
    # then twenty zero bytes. This fixed marker is not padding.
    output.extend(bytes(4) + struct.pack("<I", 0x7F) + bytes(20))

    frame_offset = 0
    for width in widths:
        packet_frames = width // 2
        left = bytearray()
        right = bytearray()
        for frame in range(frame_offset, frame_offset + packet_frames):
            left_sample, right_sample = struct.unpack_from("<hh", pcm, frame * 4)
            left.extend(struct.pack(">h", left_sample))
            right.extend(struct.pack(">h", right_sample))
        output.extend(struct.pack(">4sI", b"BLCK", width))
        output.extend(bytes(24))
        output.extend(left)
        output.extend(right)
        frame_offset += packet_frames
    return bytes(output)


def parse_ast(
    native: bytes, *, asset_id: str = "fixture", info: PCMFormat = INFO
) -> ParsedAST:
    """Parse one canonical packet layout into metadata and interleaved s16le."""

    def refuse(reason: str) -> None:
        raise NativeValidationError(asset_id, reason)

    if len(native) < 64:
        refuse("truncated STRM header")
    (
        magic,
        file_size,
        codec,
        bits,
        channels,
        loop_flag,
        rate,
        frames,
        start,
        end,
        first,
    ) = struct.unpack_from(">4sI4H5I", native)
    if magic != b"STRM":
        refuse("invalid STRM magic")
    if file_size != len(native) - 64:
        refuse("STRM file size mismatch")
    widths = _canonical_block_widths(info.frames)
    decoded = bytearray()
    offset = 64
    frame_offset = 0
    for expected_width in widths:
        if offset + 32 > len(native):
            refuse("truncated BLCK header")
        tag, width = struct.unpack_from(">4sI", native, offset)
        if tag != b"BLCK":
            refuse("invalid BLCK tag")
        if width % 2:
            refuse("odd AST block size")
        if width != expected_width:
            refuse("noncanonical AST block size/partition")
        if any(native[offset + 8 : offset + 32]):
            refuse("nonzero BLCK padding")
        payload_start = offset + 32
        payload_end = payload_start + 2 * width
        if payload_end > len(native):
            refuse("truncated BLCK payload")
        packet_frames = width // 2
        for frame in range(packet_frames):
            left_pos = payload_start + frame * 2
            right_pos = payload_start + width + frame * 2
            left = struct.unpack_from(">h", native, left_pos)[0]
            right = struct.unpack_from(">h", native, right_pos)[0]
            decoded.extend(struct.pack("<hh", left, right))
        frame_offset += packet_frames
        offset = payload_end

    if offset != len(native):
        refuse("unexpected trailing AST bytes")
    if frame_offset != info.frames:
        refuse("AST block frame count mismatch")

    return ParsedAST(
        codec=codec,
        bits=bits,
        channels=channels,
        loop_flag=loop_flag,
        rate=rate,
        frames=frames,
        loop_start=start,
        loop_end=end,
        first_block_size=first,
        header_extension=native[36:64],
        block_widths=widths,
        pcm=bytes(decoded),
    )


def validate_fixture(
    native: bytes,
    expected_pcm: bytes,
    *,
    asset_id: str = "fixture",
    info: PCMFormat = INFO,
    loop_start: int = LOOP_START,
    loop_end: int = LOOP_END,
) -> int:
    """Refuse any AST bytes that canonical reconstruction would normalize."""

    def refuse(reason: str) -> None:
        raise NativeValidationError(asset_id, reason)

    if len(expected_pcm) != info.frames * info.frame_bytes:
        refuse("invalid expected PCM length")
    parsed = parse_ast(native, asset_id=asset_id, info=info)

    if parsed.codec != 1:
        refuse("unsupported AST codec")
    if parsed.bits != 16:
        refuse("unsupported AST bit depth")
    if parsed.channels != CHANNELS:
        refuse("unsupported AST channel count")
    if parsed.loop_flag != 0xFFFF:
        refuse("AST loop flag mismatch")
    if parsed.rate != info.rate:
        refuse("AST sample rate mismatch")
    if parsed.frames != info.frames:
        refuse("AST frame count mismatch")
    if (parsed.loop_start, parsed.loop_end) != (loop_start, loop_end):
        refuse("AST loop bounds mismatch")

    widths = _canonical_block_widths(info.frames)
    if parsed.first_block_size != widths[0]:
        refuse("noncanonical STRM first block size/partition")
    if parsed.header_extension != bytes(4) + struct.pack("<I", 0x7F) + bytes(20):
        refuse("noncanonical STRM reserved/header bytes")
    if parsed.pcm != expected_pcm:
        refuse("PCM mismatch")
    return len(parsed.block_widths)


def frame_boundary_seconds(
    frame: int, rate: int, total_frames: int, side: Boundary
) -> float:
    """Return seconds that upstream floor/ceil rounding maps to ``frame``.

    The end boundary at the exact duration is returned unchanged because
    ``pcm._regions`` maps ``seconds == duration`` directly to ``info.frames``.
    Other floating-point boundaries are nudged by one representable value at a
    time until the shared PCM editor's outward rounding is exact.
    """
    if (
        side not in ("start", "end")
        or rate <= 0
        or total_frames < 0
        or not 0 <= frame <= total_frames
    ):
        raise ValueError("invalid PCM frame boundary")
    duration = total_frames / rate
    if side == "end" and frame == total_frames:
        return duration

    seconds = frame / rate
    for _ in range(64):
        scaled = seconds * rate
        mapped = math.floor(scaled) if side == "start" else math.ceil(scaled)
        if mapped == frame:
            return seconds
        seconds = math.nextafter(seconds, math.inf if mapped < frame else -math.inf)
    raise ValueError(f"could not represent {side} frame boundary {frame}")


def _merge_ranges(ranges: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


def group_edits(
    assets: Mapping[str, bytes],
    edits: Sequence[Edit],
    *,
    total_frames: int = FRAMES,
) -> dict[str, list[tuple[int, int]]]:
    """Map segment-relative ranges to native assets and merge touching spans."""
    if not edits or total_frames <= 0:
        raise ValueError("no required edits")
    groups: dict[str, list[tuple[int, int]]] = {}
    for edit in edits:
        if edit.asset not in assets:
            raise NativeValidationError(edit.asset, "unknown required asset")
        if not (
            0 <= edit.segment_start < total_frames
            and 0 < edit.segment_frames <= total_frames - edit.segment_start
            and 0 <= edit.start < edit.end <= edit.segment_frames
        ):
            raise NativeValidationError(edit.asset, "invalid segment mapping or edit")
        groups.setdefault(edit.asset, []).append(
            (edit.segment_start + edit.start, edit.segment_start + edit.end)
        )
    return {asset: _merge_ranges(ranges) for asset, ranges in groups.items()}


def _pcm_blocks_for(path: Path, info: PCMFormat) -> Iterable[bytes]:
    with path.open("rb") as stream:
        while block := stream.read(BLOCK_FRAMES * info.frame_bytes):
            yield block


def _verify_edited_pcm(
    asset_id: str,
    original: bytes,
    edited: bytes,
    ranges: Sequence[tuple[int, int]],
    info: PCMFormat,
) -> None:
    """Independently check required silence and bit-exact unaffected frames."""
    expected_size = info.frames * info.frame_bytes
    if len(original) != expected_size or len(edited) != expected_size:
        raise EditError(asset_id, "frame count changed")

    silence = bytes(info.frame_bytes)
    range_index = 0
    for frame in range(info.frames):
        while range_index < len(ranges) and frame >= ranges[range_index][1]:
            range_index += 1
        inside_edit = (
            range_index < len(ranges)
            and ranges[range_index][0] <= frame < ranges[range_index][1]
        )
        start = frame * info.frame_bytes
        end = start + info.frame_bytes
        if inside_edit:
            if edited[start:end] != silence:
                raise EditError(asset_id, "required edit incomplete")
        elif edited[start:end] != original[start:end]:
            raise EditError(asset_id, "unaffected frames changed")


def _validate_ast_native(
    asset_id: str, native: bytes, pcm: bytes, info: PCMFormat
) -> None:
    validate_fixture(native, pcm, asset_id=asset_id, info=info)


def _verify_exact_reconstruction(
    asset_id: str,
    original: bytes,
    edited: bytes,
    decoded: bytes,
    ranges: Sequence[tuple[int, int]],
    info: PCMFormat,
) -> None:
    del original, ranges
    if len(decoded) != info.frames * info.frame_bytes:
        raise ValueError("rebuilt PCM frame count changed")
    if decoded != edited:
        raise ValueError("rebuilt native decoded PCM mismatch")
    del asset_id


def prepare(
    root: Path,
    assets: Mapping[str, bytes],
    originals: Mapping[str, bytes],
    edits: Sequence[Edit],
    *,
    decoder: Decoder,
    encoder: Encoder,
    storage: WaveStorage | None = None,
    info: PCMFormat = INFO,
    native_extension: str = ".ast",
    native_validator: NativeValidator | None = None,
    reconstruction_verifier: ReconstructionVerifier | None = None,
) -> dict[str, bytes]:
    """Prepare every affected asset privately; return only after all validate.

    The defaults retain the strict AST profile. A sibling isolated experiment may
    supply only its native validator and decoded-output verifier while reusing
    this bounded PCM/scratch orchestration.
    """
    if not native_extension.startswith(".") or "/" in native_extension:
        raise ValueError("native extension must be a simple dotted suffix")
    groups = group_edits(assets, edits, total_frames=info.frames)
    if assets.keys() != originals.keys():
        raise ValueError("fixture asset/original identity mismatch")
    root.mkdir(parents=True, exist_ok=True)
    pcm_storage = storage or WaveStorage()
    validate_native = native_validator or _validate_ast_native
    verify_reconstruction = reconstruction_verifier or _verify_exact_reconstruction
    staged: dict[str, bytes] = {}

    with tempfile.TemporaryDirectory(prefix="native-prepare-", dir=root) as private:
        working = Path(private)
        for index, (asset_id, ranges) in enumerate(groups.items()):
            native = assets[asset_id]
            original_pcm = originals[asset_id]
            validate_native(asset_id, native, original_pcm, info)
            directory = working / str(index)
            directory.mkdir()
            source = directory / f"source{native_extension}"
            extracted = directory / "extracted.pcm"
            edited = directory / "edited.pcm"
            rebuilt = directory / f"rebuilt{native_extension}"
            validated_pcm = directory / "validated.pcm"
            source.write_bytes(native)

            try:
                decoder(asset_id, source, extracted, info)
                extracted_pcm = extracted.read_bytes()
                if extracted_pcm != original_pcm:
                    raise ValueError("extracted PCM differs from verified source")
            except Exception as exc:
                detail = str(exc) or type(exc).__name__
                raise ExtractionError(asset_id, detail) from exc

            expected_pcm: bytes
            try:
                with audio_scratch(directory / "scratch", pcm_storage) as scratch:
                    scratch.write_source(info, _pcm_blocks_for(extracted, info))
                    seconds = [
                        (
                            frame_boundary_seconds(
                                start, info.rate, info.frames, "start"
                            ),
                            frame_boundary_seconds(end, info.rate, info.frames, "end"),
                        )
                        for start, end in ranges
                    ]
                    result = scratch.edit(seconds, before=0, after=0, fade=0)
                    with (
                        pcm_storage.open(result) as reader,
                        edited.open("xb") as output,
                    ):
                        if reader.info != info:
                            raise ValueError("intermediate PCM metadata mismatch")
                        for block in reader.blocks():
                            output.write(block)
                expected_pcm = edited.read_bytes()
                if source.read_bytes() != native:
                    raise ValueError("native source changed during PCM edit")
            except Exception as exc:
                detail = str(exc) or type(exc).__name__
                raise EditError(asset_id, detail) from exc

            _verify_edited_pcm(asset_id, original_pcm, expected_pcm, ranges, info)

            try:
                encoder(asset_id, edited, rebuilt, info)
                native_output = rebuilt.read_bytes()
                validate_native(asset_id, native_output, expected_pcm, info)
                decoder(asset_id, rebuilt, validated_pcm, info)
                verify_reconstruction(
                    asset_id,
                    original_pcm,
                    expected_pcm,
                    validated_pcm.read_bytes(),
                    ranges,
                    info,
                )
                if source.read_bytes() != native:
                    raise ValueError("native source changed during reconstruction")
            except Exception as exc:
                detail = (
                    exc.detail
                    if isinstance(exc, NativeStageError)
                    else (str(exc) or type(exc).__name__)
                )
                raise ReconstructionError(asset_id, detail) from exc
            staged[asset_id] = native_output

        if staged.keys() != groups.keys():
            raise ValueError("incomplete native preparation")
    return staged
