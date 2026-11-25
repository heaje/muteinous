"""Manual FFmpeg identity/canonical-byte check; not a production adapter."""

import struct
from pathlib import Path
from tempfile import TemporaryDirectory

from .ast_core import (
    FRAMES,
    INFO,
    NativeValidationError,
    build_canonical_ast,
    validate_fixture,
)
from .ffmpeg_tools import FFmpegTools


def _pcm_fixture() -> bytes:
    return b"".join(
        struct.pack(
            "<hh",
            (frame * 67) % 65_536 - 32_768,
            32_767 - (frame * 137) % 65_536,
        )
        for frame in range(FRAMES)
    )


def _expect_refusal(operation: object, reason: str) -> None:
    try:
        validate_fixture(operation, _pcm_fixture())  # type: ignore[arg-type]
    except NativeValidationError as exc:
        if reason not in str(exc):
            raise AssertionError(f"wrong refusal for {reason}: {exc}") from exc
    else:
        raise AssertionError(f"unexpected acceptance: {reason}")


def main() -> None:
    tools = FFmpegTools.discover()
    print(f"PASS: {tools.version}")
    print("PASS: FFmpeg AST muxer/demuxer and pcm_s16be_planar are available")
    expected = _pcm_fixture()

    with TemporaryDirectory(prefix="muteinous-ast-probe-") as scratch:
        root = Path(scratch)
        raw = root / "input.pcm"
        source = root / "source.ast"
        extracted = root / "extracted.pcm"
        rebuilt = root / "rebuilt.ast"
        raw.write_bytes(expected)

        tools.encode("probe", raw, source, INFO)
        original = source.read_bytes()
        blocks = validate_fixture(original, expected, asset_id="probe")
        oracle = build_canonical_ast(expected, INFO)
        if original != oracle:
            raise AssertionError("FFmpeg bytes differ from pure-Python canonical AST")

        tools.decode("probe", source, extracted, INFO)
        if extracted.read_bytes() != expected:
            raise AssertionError("FFmpeg decode differs from synthetic PCM")
        tools.encode("probe", extracted, rebuilt, INFO)
        output = rebuilt.read_bytes()
        validate_fixture(output, expected, asset_id="probe")
        if output != original:
            raise AssertionError("native bytes changed during identity round trip")
        tools.assert_stereo(rebuilt)
        if source.read_bytes() != original:
            raise AssertionError("source AST changed")

        _expect_refusal(original[:-1], "STRM file size mismatch")
        unsupported = bytearray(original)
        struct.pack_into(">H", unsupported, 8, 0)
        _expect_refusal(bytes(unsupported), "unsupported AST codec")
        reserved = bytearray(original)
        reserved[36] = 1
        _expect_refusal(bytes(reserved), "noncanonical STRM reserved/header bytes")
        print(
            f"PASS: {FRAMES} stereo PCM16 frames, {blocks} canonical blocks, "
            f"{len(output)} native bytes"
        )
        print("PASS: FFmpeg output equals the pure-Python writer and identity rebuild")
        print("PASS: malformed, unsupported, and noncanonical AST inputs refused")

    if root.exists():
        raise AssertionError("probe scratch was not removed")
    print("PASS: disposable scratch removed")


if __name__ == "__main__":
    main()
