"""Stacked synthetic experiment using the actual M1.4 audio boundary.

Run from repository root in the locked environment:
    python -m experiments.native_ast.shared_edit
Only generated fixtures are accepted; no installation or arbitrary input paths.
"""

import struct
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from muteinous.core.audio.pcm import BLOCK_FRAMES, PCMFormat
from muteinous.core.audio.scratch import audio_scratch
from muteinous.core.audio.wav import WaveStorage

from .probe import FRAMES, RATE, encode, ffmpeg, require, validate_fixture

INFO = PCMFormat(RATE, 2, "s16", FRAMES, 0)


@dataclass(frozen=True)
class Edit:
    asset: str
    segment_start: int
    segment_frames: int
    start: int
    end: int


def group_edits(
    assets: dict[str, bytes], edits: tuple[Edit, ...]
) -> dict[str, list[tuple[int, int]]]:
    groups: dict[str, list[tuple[int, int]]] = {}
    require(bool(edits), "no required edits")
    for edit in edits:
        require(edit.asset in assets, "unknown required asset")
        require(
            0 <= edit.segment_start < FRAMES
            and 0 < edit.segment_frames <= FRAMES - edit.segment_start
            and 0 <= edit.start < edit.end <= edit.segment_frames,
            "invalid segment mapping or edit",
        )
        groups.setdefault(edit.asset, []).append(
            (edit.segment_start + edit.start, edit.segment_start + edit.end)
        )
    return groups


def blocks(path: Path) -> Iterator[bytes]:
    with path.open("rb") as stream:
        while block := stream.read(BLOCK_FRAMES * INFO.frame_bytes):
            yield block


def expected_edit(pcm: bytes, ranges: list[tuple[int, int]]) -> bytes:
    """Independent zero-margin test oracle, not the reconstruction edit path."""
    require(len(pcm) == FRAMES * INFO.frame_bytes, "invalid fixture PCM length")
    result = bytearray(pcm)
    for start, end in ranges:
        result[start * 4 : end * 4] = bytes((end - start) * 4)
    return bytes(result)


def prepare(
    root: Path,
    assets: dict[str, bytes],
    originals: dict[str, bytes],
    edits: tuple[Edit, ...],
    *,
    fail_asset: str | None = None,
) -> dict[str, bytes]:
    """Small fixture-only preparation; nothing escapes unless every edit validates."""
    groups = group_edits(assets, edits)
    require(assets.keys() == originals.keys(), "fixture identity mismatch")
    storage = WaveStorage()
    staged: dict[str, bytes] = {}
    with TemporaryDirectory(prefix="prepare-", dir=root) as private:
        working = Path(private)
        for index, (asset, ranges) in enumerate(groups.items()):
            try:
                native = assets[asset]
                original_pcm = originals[asset]
                validate_fixture(native, original_pcm)
                directory = working / str(index)
                directory.mkdir()
                source = directory / "source.ast"
                extracted = directory / "extracted.pcm"
                edited = directory / "edited.pcm"
                rebuilt = directory / "rebuilt.ast"
                decoded = directory / "validated.pcm"
                source.write_bytes(native)
                ffmpeg("-i", str(source), "-c:a", "pcm_s16le", "-f", "s16le", str(extracted))
                require(extracted.read_bytes() == original_pcm, "extraction fidelity failure")
                expected = expected_edit(original_pcm, ranges)
                with audio_scratch(directory / "scratch", storage) as scratch:
                    scratch.write_source(INFO, blocks(extracted))
                    # Segment-relative requests are mapped to known asset frames.
                    # No margins/fades: translating the requests cannot cross segments.
                    result = scratch.edit(
                        [(a / RATE, b / RATE) for a, b in ranges],
                        before=0, after=0, fade=0,
                    )
                    with storage.open(result) as reader, edited.open("xb") as output:
                        require(reader.info == INFO, "intermediate metadata mismatch")
                        for block in reader.blocks():
                            output.write(block)
                require(edited.read_bytes() == expected, "required PCM edit mismatch")
                if asset == fail_asset:
                    # Real reconstruction subprocess failure, not a skipped asset.
                    edited.unlink()
                encode(edited, rebuilt)
                native_output = rebuilt.read_bytes()
                validate_fixture(native_output, expected)
                # The independent native parser and an actual native decoder must agree.
                ffmpeg("-i", str(rebuilt), "-c:a", "pcm_s16le", "-f", "s16le", str(decoded))
                require(decoded.read_bytes() == expected, "rebuilt decoder mismatch")
                require(source.read_bytes() == native, "source changed")
                staged[asset] = native_output
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                raise ValueError(f"required asset {asset}: {exc}") from exc
        require(staged.keys() == groups.keys(), "incomplete preparation")
    return staged


def main() -> None:
    with TemporaryDirectory(prefix="muteinous-ast-shared-") as private:
        root = Path(private)
        originals = {
            name: b"".join(
                struct.pack("<hh", (i * 67 + seed) % 65536 - 32768,
                            32767 - (i * 137 + seed) % 65536)
                for i in range(FRAMES)
            )
            for name, seed in (("a", 0), ("b", 19), ("untouched", 31))
        }
        assets: dict[str, bytes] = {}
        for name, pcm in originals.items():
            raw = root / f"{name}.pcm"
            native = root / f"{name}.ast"
            raw.write_bytes(pcm)
            encode(raw, native)
            assets[name] = native.read_bytes()
            validate_fixture(assets[name], pcm)
        edits = (
            Edit("a", 0, 4096, 1024, 1152),
            Edit("a", 4096, 4096, 0, 128),
            Edit("b", 0, 4096, 2048, 2176),
        )
        before = set(root.iterdir())
        staged = prepare(root, assets, originals, edits)
        require(set(staged) == {"a", "b"}, "wrong affected grouping")
        require(staged["a"] != assets["a"] and staged["b"] != assets["b"], "no native change")
        for name, native in assets.items():
            require((root / f"{name}.ast").read_bytes() == native, "original asset changed")
        require(set(root.iterdir()) == before, "preparation scratch leaked")
        for kind in ("corrupt", "unsupported", "reconstruction"):
            bad = dict(assets)
            if kind == "corrupt":
                bad["b"] = bad["b"][:-1]
            elif kind == "unsupported":
                bad["b"] = bad["b"][:8] + b"\x00\x00" + bad["b"][10:]
            try:
                prepare(root, bad, originals, edits,
                        fail_asset="b" if kind == "reconstruction" else None)
            except ValueError as exc:
                require("required asset b:" in str(exc), f"unexpected failure: {exc}")
            else:
                raise ValueError(f"unexpected successful preparation: {kind}")
            require(set(root.iterdir()) == before, "failed preparation scratch leaked")
        print("PASS: actual shared PCM/WaveStorage edit, two grouped edits in a, one in b")
        print("PASS: independent AST validation, unaffected PCM and native asset preservation")
        print("PASS: corrupt, unsupported and reconstruction failure refuse the entire request")
    require(not root.exists(), "scratch cleanup failed")


if __name__ == "__main__":
    main()
