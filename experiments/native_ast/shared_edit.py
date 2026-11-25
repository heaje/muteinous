"""Manual FFmpeg exercise of the actual M1.4 shared PCM and scratch APIs.

Run from the repository root:
    .venv/Scripts/python.exe -m experiments.native_ast.shared_edit
Only generated fixtures are accepted; no installation or arbitrary input paths.
"""

import struct
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory

from muteinous.core.audio.pcm import PCMFormat
from muteinous.core.audio.wav import WaveStorage

from .ast_core import (
    FRAMES,
    INFO,
    Edit,
    NativeStageError,
    NativeValidationError,
    ReconstructionError,
    build_canonical_ast,
    prepare,
    validate_fixture,
)
from .ffmpeg_tools import FFmpegTools


def _original_pcm(seed: int) -> bytes:
    return b"".join(
        struct.pack(
            "<hh",
            (frame * 67 + seed) % 65_536 - 32_768,
            32_767 - (frame * 137 + seed) % 65_536,
        )
        for frame in range(FRAMES)
    )


def _expected_edit(pcm: bytes, ranges: list[tuple[int, int]]) -> bytes:
    edited = bytearray(pcm)
    for start, end in ranges:
        edited[start * INFO.frame_bytes : end * INFO.frame_bytes] = bytes(
            (end - start) * INFO.frame_bytes
        )
    return bytes(edited)


def _snapshot(root: Path) -> tuple[dict[str, bytes], tuple[str, ...]]:
    files = {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    directories = tuple(
        sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_dir())
    )
    return files, directories


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _assert_failure(
    root: Path,
    assets: dict[str, bytes],
    originals: dict[str, bytes],
    edits: tuple[Edit, ...],
    decoder: Callable[..., None],
    encoder: Callable[..., None],
    expected_type: type[NativeStageError],
    expected_message: str,
) -> None:
    before = _snapshot(root)
    try:
        prepare(
            root,
            assets,
            originals,
            edits,
            decoder=decoder,
            encoder=encoder,
            storage=WaveStorage(),
        )
    except NativeStageError as exc:
        _require(type(exc) is expected_type, f"unexpected exception type: {exc!r}")
        _require(expected_message in str(exc), f"unexpected exception message: {exc}")
    else:
        raise AssertionError(f"expected {expected_type.__name__}")
    _require(
        _snapshot(root) == before, "failed preparation changed files or directories"
    )


def main() -> None:
    tools = FFmpegTools.discover()
    print(f"PASS: {tools.version}")
    print("PASS: FFmpeg AST muxer/demuxer and pcm_s16be_planar are available")

    with TemporaryDirectory(prefix="muteinous-ast-shared-") as private:
        root = Path(private)
        originals = {
            asset: _original_pcm(seed)
            for asset, seed in (("a", 0), ("b", 19), ("untouched", 31))
        }
        assets: dict[str, bytes] = {}
        for asset, pcm in originals.items():
            raw = root / f"{asset}.pcm"
            native_path = root / f"{asset}.ast"
            raw.write_bytes(pcm)
            tools.encode(asset, raw, native_path, INFO)
            native = native_path.read_bytes()
            validate_fixture(native, pcm, asset_id=asset)
            if native != build_canonical_ast(pcm, INFO):
                raise AssertionError(
                    f"FFmpeg {asset} bytes differ from canonical writer"
                )
            assets[asset] = native

        edits = (
            Edit("a", 0, 4096, 1001, 1080),
            Edit("a", 1040, 2048, 40, 120),
            Edit("a", 1100, 2048, 30, 157),
            Edit("a", 4000, 1024, 0, 50),
            Edit("b", 0, 4096, 2048, 2176),
        )
        encode_calls: list[str] = []
        decode_calls: list[str] = []

        def counted_encoder(
            asset_id: str, pcm_path: Path, native_path: Path, info: PCMFormat
        ) -> None:
            encode_calls.append(asset_id)
            tools.encode(asset_id, pcm_path, native_path, info)

        def counted_decoder(
            asset_id: str, native_path: Path, pcm_path: Path, info: PCMFormat
        ) -> None:
            decode_calls.append(asset_id)
            tools.decode(asset_id, native_path, pcm_path, info)

        before = _snapshot(root)
        staged = prepare(
            root,
            assets,
            originals,
            edits,
            decoder=counted_decoder,
            encoder=counted_encoder,
            storage=WaveStorage(),
        )
        if set(staged) != {"a", "b"}:
            raise AssertionError("wrong affected asset grouping")
        if Counter(encode_calls) != Counter({"a": 1, "b": 1}):
            raise AssertionError(f"unexpected encoder calls: {encode_calls}")
        if "untouched" in encode_calls:
            raise AssertionError("untouched asset was rebuilt")

        merged_a = [(1001, 1257), (4000, 4050)]
        expected = {
            "a": _expected_edit(originals["a"], merged_a),
            "b": _expected_edit(originals["b"], [(2048, 2176)]),
        }
        for asset, pcm in expected.items():
            validate_fixture(staged[asset], pcm, asset_id=asset)
            rebuilt_path = root / f"rebuilt-{asset}.ast"
            decoded_path = root / f"rebuilt-{asset}.pcm"
            rebuilt_path.write_bytes(staged[asset])
            tools.assert_stereo(rebuilt_path)
            tools.decode(asset, rebuilt_path, decoded_path, INFO)
            _require(decoded_path.read_bytes() == pcm, f"{asset} decoded PCM mismatch")
            rebuilt_path.unlink()
            decoded_path.unlink()
        _require(
            _snapshot(root) == before, "successful preparation leaked scratch data"
        )
        for asset in originals:
            _require(
                (root / f"{asset}.ast").read_bytes() == assets[asset], "source changed"
            )

        corrupt = dict(assets)
        corrupt["b"] = corrupt["b"][:-1]
        _assert_failure(
            root,
            corrupt,
            originals,
            edits,
            counted_decoder,
            counted_encoder,
            NativeValidationError,
            "required asset b: native validation: STRM file size mismatch",
        )

        unsupported = dict(assets)
        malformed = bytearray(unsupported["b"])
        struct.pack_into(">H", malformed, 8, 0)
        unsupported["b"] = bytes(malformed)
        _assert_failure(
            root,
            unsupported,
            originals,
            edits,
            counted_decoder,
            counted_encoder,
            NativeValidationError,
            "required asset b: native validation: unsupported AST codec",
        )

        expected_b = _expected_edit(originals["b"], [(2048, 2176)])

        def refusing_encoder(
            asset_id: str, pcm_path: Path, native_path: Path, info: PCMFormat
        ) -> None:
            if asset_id == "b":
                _require(pcm_path.is_file(), "edited PCM missing at encoder stage")
                _require(
                    pcm_path.read_bytes() == expected_b,
                    "encoder failure did not receive valid edited PCM",
                )
                native_path.write_bytes(b"pre-existing destination")
            tools.encode(asset_id, pcm_path, native_path, info)

        _assert_failure(
            root,
            assets,
            originals,
            edits,
            counted_decoder,
            refusing_encoder,
            ReconstructionError,
            "already exists",
        )
        _assert_failure(
            root,
            assets,
            originals,
            tuple(reversed(edits)),
            counted_decoder,
            refusing_encoder,
            ReconstructionError,
            "already exists",
        )

        _require(not list(root.glob("native-prepare-*")), "prepare scratch leaked")

    if root.exists():
        raise AssertionError("shared-edit scratch was not removed")
    print("PASS: real PCMFormat/WaveStorage/Scratch.edit preserved stereo mask 3")
    print("PASS: touching/overlapping edits merged; one rebuild per affected asset")
    print("PASS: untouched asset not rebuilt; decoded edited PCM is frame-exact")
    print("PASS: native refusals and real -n encoder failures are all-or-nothing")
    print(
        "PASS: later-asset and first-asset failures preserve snapshots and clean scratch"
    )
    print("PASS: disposable scratch removed")


if __name__ == "__main__":
    main()
