"""Verify native byte preservation on the canonical synthetic AST profile."""

from pathlib import Path
from tempfile import TemporaryDirectory

from muteinous.core.audio.wav import WaveStorage

from .ast_core import INFO, Edit, prepare, validate_fixture
from .ffmpeg_tools import FFmpegTools
from .shared_edit import _expected_edit, _original_pcm, _snapshot


def main() -> None:
    tools = FFmpegTools.discover()
    print(tools.version)
    ranges = {"a": [(1001, 1257), (4000, 4050)], "b": [(2048, 2176)]}
    with TemporaryDirectory(prefix="muteinous-ast-byte-fidelity-") as temporary:
        root = Path(temporary)
        originals = {
            name: _original_pcm(seed)
            for name, seed in (("a", 0), ("b", 19), ("untouched", 31))
        }
        assets = {}
        for name, pcm in originals.items():
            raw = root / f"{name}.pcm"
            native = root / f"{name}.ast"
            raw.write_bytes(pcm)
            tools.encode(name, raw, native, INFO)
            assets[name] = native.read_bytes()
        before = _snapshot(root)
        edits = tuple(
            Edit(name, 0, INFO.frames, start, end)
            for name, spans in ranges.items()
            for start, end in spans
        )
        staged = prepare(
            root,
            assets,
            originals,
            edits,
            decoder=tools.decode,
            encoder=tools.encode,
            storage=WaveStorage(),
        )
        if set(staged) != set(ranges) or _snapshot(root) != before:
            raise AssertionError("grouping or source/scratch integrity mismatch")
        for name, output in staged.items():
            validate_fixture(
                output, _expected_edit(originals[name], ranges[name]), asset_id=name
            )
            expected_native = bytearray(assets[name])
            edited_frames = {
                frame for start, end in ranges[name] for frame in range(start, end)
            }
            # Four blocks, each with a 32-byte header and two 4096-byte planes
            # of big-endian signed 16-bit samples, after the 64-byte header.
            for frame in edited_frames:
                block, local_frame = divmod(frame, 2048)
                for channel in range(2):
                    offset = (
                        64 + block * (32 + 8192) + 32 + channel * 4096 + local_frame * 2
                    )
                    expected_native[offset : offset + 2] = b"\x00\x00"
            if output != expected_native:
                raise AssertionError(f"{name}: unexpected native bytes")
            print(
                f"{name}: {len(output)} native bytes, {len(edited_frames)} edited frames, "
                f"{len(output) - 4 * len(edited_frames)} bytes outside edited sample "
                "positions identical"
            )
    print("PASS: exact native byte preservation, grouping and cleanup")


if __name__ == "__main__":
    main()
