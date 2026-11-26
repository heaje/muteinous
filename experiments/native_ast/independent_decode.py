"""Verify synthetic AST source and edited output with independent vgmstream."""

import argparse
import json
import subprocess
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from muteinous.core.audio.wav import WaveStorage

from .ast_core import INFO, LOOP_END, LOOP_START, Edit, prepare, validate_fixture
from .ffmpeg_tools import FFmpegTools
from .shared_edit import _expected_edit, _original_pcm


def _run(arguments: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        arguments,
        check=True,
        capture_output=True,
        timeout=30,
    )


def _metadata(cli: Path, native: Path) -> dict[str, Any]:
    result = _run([str(cli), "-I", str(native)])
    try:
        metadata = json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssertionError(
            f"vgmstream metadata was not valid JSON: {native}"
        ) from exc
    if not isinstance(metadata, dict):
        raise AssertionError("vgmstream metadata was not a JSON object")
    expected = {
        "sampleRate": INFO.rate,
        "channels": INFO.channels,
        "numberOfSamples": INFO.frames,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise AssertionError(
                f"vgmstream {key} mismatch for {native.name}: "
                f"{metadata.get(key)!r} != {value!r}"
            )
    looping = metadata.get("loopingInfo")
    if not isinstance(looping, dict) or (
        looping.get("start"),
        looping.get("end"),
    ) != (LOOP_START, LOOP_END):
        raise AssertionError(f"vgmstream loop points mismatch for {native.name}")
    return metadata


def _decode(cli: Path, native: Path, output: Path, expected_pcm: bytes) -> None:
    _run([str(cli), "-i", "-o", str(output), str(native)])
    with wave.open(str(output), "rb") as wav:
        properties = (
            wav.getnchannels(),
            wav.getframerate(),
            wav.getnframes(),
            wav.getsampwidth(),
            wav.getcomptype(),
        )
        if properties != (INFO.channels, INFO.rate, INFO.frames, 2, "NONE"):
            raise AssertionError(f"vgmstream WAV properties mismatch: {properties}")
        decoded = wav.readframes(wav.getnframes())
    if decoded != expected_pcm:
        raise AssertionError(f"vgmstream sample-exact PCM mismatch for {native.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--vgmstream-cli",
        type=Path,
        required=True,
        help="path to the official vgmstream-cli executable",
    )
    cli = parser.parse_args().vgmstream_cli.resolve(strict=True)

    tools = FFmpegTools.discover()
    print(f"FFmpeg extraction/reconstruction: {tools.version}")
    with TemporaryDirectory(prefix="muteinous-ast-independent-") as temporary:
        root = Path(temporary)
        originals = {
            asset: _original_pcm(seed)
            for asset, seed in (("a", 0), ("b", 19), ("untouched", 31))
        }
        assets: dict[str, bytes] = {}
        paths: dict[str, Path] = {}
        for asset, pcm in originals.items():
            raw = root / f"{asset}.pcm"
            native_path = root / f"{asset}.ast"
            raw.write_bytes(pcm)
            tools.encode(asset, raw, native_path, INFO)
            assets[asset] = native_path.read_bytes()
            paths[asset] = native_path

        stage = root / "stage"
        stage.mkdir()
        source_bytes = {asset: path.read_bytes() for asset, path in paths.items()}
        edits = (
            Edit("a", 0, 4096, 1001, 1080),
            Edit("a", 1040, 2048, 40, 120),
            Edit("a", 1100, 2048, 30, 157),
            Edit("a", 0, 4096, 4000, 4050),
            Edit("b", 0, 4096, 2048, 2176),
        )
        staged = prepare(
            stage,
            assets,
            originals,
            edits,
            decoder=tools.decode,
            encoder=tools.encode,
            storage=WaveStorage(),
        )
        if set(staged) != {"a", "b"} or list(stage.iterdir()):
            raise AssertionError("grouping or preparation scratch mismatch")

        expected_edits = {
            "a": _expected_edit(originals["a"], [(1001, 1257), (4000, 4050)]),
            "b": _expected_edit(originals["b"], [(2048, 2176)]),
        }
        for asset in originals:
            source = paths[asset]
            source_info = _metadata(cli, source)
            _decode(cli, source, root / f"{asset}.source.wav", originals[asset])
            if asset not in staged:
                if source_info["loopingInfo"] != {
                    "start": LOOP_START,
                    "end": LOOP_END,
                }:
                    raise AssertionError("unexpected untouched-source loop metadata")
                continue

            edited_path = root / f"{asset}.edited.ast"
            edited_path.write_bytes(staged[asset])
            validate_fixture(staged[asset], expected_edits[asset], asset_id=asset)
            _metadata(cli, edited_path)
            _decode(
                cli,
                edited_path,
                root / f"{asset}.edited.wav",
                expected_edits[asset],
            )
            print(
                f"PASS: {asset} source and edited AST independently decoded "
                "sample-exactly; 32000 Hz stereo, 8192 frames, "
                f"loops {LOOP_START}..{LOOP_END}"
            )
        if any(
            paths[asset].read_bytes() != native
            for asset, native in source_bytes.items()
        ):
            raise AssertionError("independent decoding changed an original AST source")

    print("PASS: vgmstream independent AST validation and cleanup")


if __name__ == "__main__":
    main()
