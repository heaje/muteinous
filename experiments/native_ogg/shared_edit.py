"""Manual real-FFmpeg exercise of shared PCM, Ogg rebuilding and refusals."""

from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from experiments.native_ast.ast_core import (
    Decoder,
    Edit,
    Encoder,
    NativeStageError,
    NativeValidationError,
    ReconstructionError,
)
from muteinous.core.audio.pcm import PCMFormat
from muteinous.core.audio.wav import WaveStorage

from .ffmpeg_tools import OggFFmpegTools
from .manual_support import create_source_assets, snapshot
from .ogg_core import build_ogg_fixture, parse_ogg_vorbis
from .ogg_prepare import (
    INFO,
    QualityPolicy,
    measure_lossy_effects,
    prepare_ogg,
)

QUALITY = QualityPolicy()


def _expected(pcm: bytes, ranges: list[tuple[int, int]]) -> bytes:
    edited = bytearray(pcm)
    for start, end in ranges:
        edited[start * INFO.frame_bytes : end * INFO.frame_bytes] = bytes(
            (end - start) * INFO.frame_bytes
        )
    return bytes(edited)


def _edits() -> tuple[Edit, ...]:
    return (
        Edit("a", 0, INFO.frames, 11_025, 22_050),
        Edit("a", 21_000, INFO.frames - 21_000, 0, 7_665),
        Edit("a", 28_665, INFO.frames - 28_665, 0, 1_335),
        Edit("b", 0, INFO.frames, 35_280, 52_920),
    )


def _ranges() -> dict[str, list[tuple[int, int]]]:
    return {"a": [(11_025, 30_000)], "b": [(35_280, 52_920)]}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _refuse(
    root: Path,
    stage_root: Path,
    assets: dict[str, bytes],
    originals: dict[str, bytes],
    edits: tuple[Edit, ...],
    decoder: Decoder,
    encoder: Encoder,
    error_type: type[NativeStageError],
    reason: str,
) -> NativeStageError:
    before = snapshot(root)
    try:
        prepare_ogg(
            stage_root,
            assets,
            originals,
            edits,
            decoder=decoder,
            encoder=encoder,
            info=INFO,
            storage=WaveStorage(),
            quality=QUALITY,
        )
    except NativeStageError as exc:
        _require(type(exc) is error_type, f"wrong native stage error: {exc}")
        _require(exc.asset_id == "b", f"wrong failed asset: {exc.asset_id}")
        if reason:
            _require(reason.casefold() in str(exc).casefold(), f"wrong reason: {exc}")
        error = exc
    else:
        raise AssertionError(f"expected {error_type.__name__}")
    _require(snapshot(root) == before, "failed request changed its file snapshot")
    _require(not list(stage_root.glob("native-prepare-*")), "prepare scratch leaked")
    return error


def main() -> None:
    tools = OggFFmpegTools.discover()
    print(f"PASS: {tools.version}")
    print("PASS: Ogg muxer/demuxer, libvorbis encoder, Vorbis decoder available")

    with TemporaryDirectory(prefix="muteinous-native-ogg-edit-") as private:
        root = Path(private)
        stage_root = root / "staging"
        stage_root.mkdir()
        assets, originals, metadata = create_source_assets(
            root, tools, ("a", "b", "untouched")
        )
        source_snapshot = snapshot(root)
        encode_calls: list[str] = []
        decode_calls: list[str] = []

        def decoder(
            asset_id: str, native_path: Path, pcm_path: Path, info: PCMFormat
        ) -> None:
            decode_calls.append(asset_id)
            tools.decode(asset_id, native_path, pcm_path, info)

        expected = {
            asset: _expected(originals[asset], ranges)
            for asset, ranges in _ranges().items()
        }

        def encoder(
            asset_id: str, pcm_path: Path, native_path: Path, info: PCMFormat
        ) -> None:
            encode_calls.append(asset_id)
            _require(
                pcm_path.read_bytes() == expected[asset_id],
                f"{asset_id} encoder did not receive exactly edited intermediate PCM",
            )
            source_info = metadata[asset_id]
            tools.encode_vorbis(
                asset_id,
                pcm_path,
                native_path,
                info,
                nominal_bitrate=source_info.nominal_bitrate,
                comments=source_info.comments,
            )

        staged = prepare_ogg(
            stage_root,
            assets,
            originals,
            _edits(),
            decoder=decoder,
            encoder=encoder,
            info=INFO,
            storage=WaveStorage(),
            quality=QUALITY,
        )
        _require(set(staged) == {"a", "b"}, "wrong affected-asset grouping")
        _require(
            Counter(encode_calls) == Counter({"a": 1, "b": 1}),
            f"wrong rebuild count: {encode_calls}",
        )
        _require("untouched" not in encode_calls, "untouched Ogg was rebuilt")

        for asset_id, native in staged.items():
            parsed = parse_ogg_vorbis(native, expected_frames=INFO.frames)
            _require(
                parsed.comment_multiset == metadata[asset_id].comment_multiset,
                f"{asset_id} user comments changed",
            )
            _require(
                abs(parsed.nominal_bitrate - metadata[asset_id].nominal_bitrate)
                <= max(16_000, metadata[asset_id].nominal_bitrate * 0.15),
                f"{asset_id} nominal bitrate class changed",
            )
            output_path = root / f"{asset_id}.rebuilt.ogg"
            decoded_path = root / f"{asset_id}.rebuilt.f32le"
            output_path.write_bytes(native)
            tools.decode(asset_id, output_path, decoded_path, INFO)
            decoded = decoded_path.read_bytes()
            _require(
                len(decoded) == INFO.frames * INFO.frame_bytes,
                f"{asset_id} decoded frame count changed",
            )
            measured = measure_lossy_effects(
                originals[asset_id],
                decoded,
                _ranges()[asset_id],
                INFO,
                policy=QUALITY,
            )
            for region in measured.outside_regions:
                print(
                    f"MEASURE: {asset_id} outside [{region.start_frame},"
                    f"{region.end_frame}) SNR={region.snr_db:.3f} dB "
                    f"max_abs_error={region.maximum_absolute_error:.8f}"
                )
            for index, peak in enumerate(measured.edited_region_peaks):
                print(f"MEASURE: {asset_id} edited core {index} peak={peak:.8f}")
            print(
                f"MEASURE: {asset_id} Ogg bytes source={len(assets[asset_id])}, "
                f"rebuilt={len(native)}, delta={len(native) - len(assets[asset_id]):+d}"
            )

        _require(
            (root / "untouched.ogg").read_bytes() == assets["untouched"],
            "source untouched Ogg changed",
        )
        _require(
            Counter(decode_calls) == Counter({"a": 2, "b": 2}),
            f"unexpected decode calls: {decode_calls}",
        )
        print("PASS: shared PCMFormat/WaveStorage/Scratch.edit used f32le mask 3")
        print("PASS: exact frame mapping, merged ranges, and one rebuild per asset")
        print(
            "PASS: rebuilt Ogg structure/comments/bitrate/frame count independently checked"
        )
        print("PASS: untouched asset bytes remained unchanged")

        edits = _edits()
        corrupt = dict(assets)
        damaged = bytearray(corrupt["b"])
        damaged[-1] ^= 1
        corrupt["b"] = bytes(damaged)

        def normal_decoder(
            asset_id: str, native_path: Path, pcm_path: Path, info: PCMFormat
        ) -> None:
            tools.decode(asset_id, native_path, pcm_path, info)

        for failing_first in (False, True):
            ordered_edits = tuple(reversed(edits)) if failing_first else edits
            order = "first" if failing_first else "second"
            _refuse(
                root,
                stage_root,
                corrupt,
                originals,
                ordered_edits,
                normal_decoder,
                encoder,
                NativeValidationError,
                "Ogg page CRC mismatch",
            )
            print(f"PASS: corrupt Ogg refused at native-validation stage ({order})")

            unsupported = dict(assets)
            unsupported["b"] = build_ogg_fixture(frames=INFO.frames, channels=6)
            _refuse(
                root,
                stage_root,
                unsupported,
                originals,
                ordered_edits,
                normal_decoder,
                encoder,
                NativeValidationError,
                "unsupported Vorbis channel profile",
            )
            print(
                f"PASS: six-channel Vorbis refused at native-validation stage ({order})"
            )

            def failing_encoder(
                asset_id: str,
                pcm_path: Path,
                native_path: Path,
                info: PCMFormat,
            ) -> None:
                if asset_id == "b":
                    _require(
                        pcm_path.read_bytes() == expected["b"],
                        "encode refusal did not receive valid edited PCM",
                    )
                    native_path.write_bytes(b"pre-existing output")
                source_info = metadata[asset_id]
                tools.encode_vorbis(
                    asset_id,
                    pcm_path,
                    native_path,
                    info,
                    nominal_bitrate=source_info.nominal_bitrate,
                    comments=source_info.comments,
                )

            error = _refuse(
                root,
                stage_root,
                assets,
                originals,
                ordered_edits,
                normal_decoder,
                failing_encoder,
                ReconstructionError,
                "",
            )
            _require(
                "asset b" in str(error) and "reconstruction" in str(error),
                "encode failure did not identify asset and reconstruction stage",
            )
            _require(
                "already exists" in str(error).casefold()
                or "not overwriting" in str(error).casefold(),
                f"expected FFmpeg -n destination refusal, got {error}",
            )
            print(
                f"PASS: valid edited PCM + FFmpeg -n encode refusal was atomic ({order})"
            )

        _require(snapshot(root) != source_snapshot, "manual outputs were not created")
        _require(
            (root / "untouched.ogg").read_bytes() == assets["untouched"],
            "failure controls changed untouched source",
        )
        stage_root.rmdir()

    if root.exists():
        raise AssertionError("disposable shared-edit directory was not removed")
    print("PASS: all manual Ogg scratch removed")


if __name__ == "__main__":
    main()
