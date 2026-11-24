"""Synthetic AST feasibility checkpoint; not a censorship editor or adapter."""

import struct
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

RATE = 32000
FRAMES = 8192


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def ffmpeg(*args: str) -> None:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-n", *args],
        check=True,
        timeout=30,
    )


def encode(pcm: Path, native: Path) -> None:
    ffmpeg(
        "-f", "s16le", "-ar", str(RATE), "-ac", "2", "-i", str(pcm),
        "-c:a", "pcm_s16be_planar", "-f", "ast", "-loopstart", "32",
        "-loopend", "192", str(native),
    )


def validate_fixture(native: bytes, expected: bytes) -> int:
    """Independently check the exact synthetic profile, not arbitrary ASTs."""
    require(len(native) >= 64, "truncated STRM header")
    magic, size, codec, bits, channels, loop, rate, frames, start, end, first = (
        struct.unpack_from(">4sI4H5I", native)
    )
    require(magic == b"STRM" and size == len(native) - 64, "invalid STRM size")
    require((codec, bits, channels, loop) == (1, 16, 2, 65535), "unsupported profile")
    require((rate, frames, start, end) == (RATE, FRAMES, 1024, 6144), "metadata mismatch")
    offset = 64
    decoded = bytearray()
    blocks = 0
    while offset < len(native):
        require(offset + 32 <= len(native), "truncated BLCK header")
        tag, width = struct.unpack_from(">4sI", native, offset)
        require(tag == b"BLCK" and width > 0 and width % 2 == 0, "invalid block")
        require(blocks != 0 or width == first, "first block size mismatch")
        begin = offset + 32
        offset = begin + 2 * width
        require(offset <= len(native), "truncated block payload")
        for pos in range(begin, begin + width, 2):
            left = struct.unpack_from(">h", native, pos)[0]
            right = struct.unpack_from(">h", native, pos + width)[0]
            decoded.extend(struct.pack("<hh", left, right))
        blocks += 1
    require(len(decoded) == frames * 4 and decoded == expected, "PCM mismatch")
    require(blocks > 1, "fixture must exercise multiple blocks")
    return blocks


def expect_refusal(native: bytes, expected: bytes, reason: str) -> None:
    try:
        validate_fixture(native, expected)
    except ValueError as exc:
        require(reason in str(exc), f"wrong refusal: {exc}")
    else:
        raise ValueError(f"unexpected acceptance: {reason}")


def main() -> None:
    expected = b"".join(
        struct.pack("<hh", (i * 67) % 65536 - 32768, 32767 - (i * 137) % 65536)
        for i in range(FRAMES)
    )
    with TemporaryDirectory(prefix="muteinous-ast-probe-") as scratch:
        root = Path(scratch)
        raw = root / "input.pcm"
        source = root / "source.ast"
        extracted = root / "extracted.pcm"
        rebuilt = root / "rebuilt.ast"
        raw.write_bytes(expected)
        encode(raw, source)
        original = source.read_bytes()
        blocks = validate_fixture(original, expected)
        ffmpeg("-i", str(source), "-c:a", "pcm_s16le", "-f", "s16le", str(extracted))
        require(extracted.read_bytes() == expected, "FFmpeg decode mismatch")
        encode(extracted, rebuilt)
        output = rebuilt.read_bytes()
        validate_fixture(output, expected)
        require(output == original, "native bytes changed during identity round trip")
        require(source.read_bytes() == original, "source changed")
        expect_refusal(output[:-1], expected, "invalid STRM size")
        expect_refusal(output[:8] + b"\x00\x00" + output[10:], expected, "unsupported profile")
        expect_refusal(output[:96] + bytes([output[96] ^ 1]) + output[97:], expected, "PCM mismatch")
        print(f"PASS: {FRAMES} stereo PCM16 frames, {blocks} blocks, {len(output)} native bytes")
        print("PASS: exact native round trip; three malformed/unsupported/fidelity refusals")
    require(not root.exists(), "scratch cleanup failed")
    print("PASS: disposable scratch removed")


if __name__ == "__main__":
    main()
