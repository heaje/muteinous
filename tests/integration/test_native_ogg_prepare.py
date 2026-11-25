import math
import struct
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

import pytest

from experiments.native_ast.ast_core import (
    Decoder,
    Edit,
    EditError,
    Encoder,
    ExtractionError,
    NativeStageError,
    NativeValidationError,
    ReconstructionError,
    frame_boundary_seconds,
)
from experiments.native_ogg.ogg_core import build_ogg_fixture, parse_ogg_vorbis
from experiments.native_ogg.ogg_prepare import (
    INFO as PRODUCTION_INFO,
)
from experiments.native_ogg.ogg_prepare import (
    QualityPolicy,
    _guard_regions,
    _padded_ranges,
    measure_lossy_effects,
    prepare_ogg,
    verify_lossy_reconstruction,
)
from muteinous.core.audio.pcm import PCMFormat
from muteinous.core.audio.storage import Reader
from muteinous.core.audio.wav import WaveStorage

pytestmark = pytest.mark.portable

INFO = PCMFormat(44_100, 2, "f32", 5_000, 3)
QUALITY = QualityPolicy(
    guard_frames=64,
    padding_frames=64,
    silence_peak_limit=0.0005,
    minimum_outside_snr_db=24.0,
    maximum_outside_abs_error=0.05,
)


def _pcm(seed: int) -> bytes:
    return b"".join(
        struct.pack(
            "<ff",
            0.22 * math.sin(frame * 0.037) + seed * 0.005,
            0.18 * math.cos(frame * 0.031) - seed * 0.004,
        )
        for frame in range(INFO.frames)
    )


def _silenced(pcm: bytes, ranges: Sequence[tuple[int, int]]) -> bytes:
    result = bytearray(pcm)
    for start, end in ranges:
        result[start * INFO.frame_bytes : end * INFO.frame_bytes] = bytes(
            (end - start) * INFO.frame_bytes
        )
    return bytes(result)


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


def _assets(root: Path) -> tuple[dict[str, bytes], dict[str, bytes]]:
    originals = {
        asset: _pcm(seed) for asset, seed in (("a", 0), ("b", 2), ("untouched", 4))
    }
    assets: dict[str, bytes] = {}
    for asset in originals:
        comments = (
            ("LOOPSTART", "2205"),
            ("LOOPLENGTH", "22050"),
            ("EXPERIMENT", "native_ogg"),
            ("ASSET", asset),
        )
        native = build_ogg_fixture(frames=INFO.frames, comments=comments)
        parse_ogg_vorbis(native, expected_frames=INFO.frames)
        assets[asset] = native
        (root / f"{asset}.ogg").write_bytes(native)
    return assets, originals


def _edits() -> tuple[Edit, ...]:
    return (
        Edit("a", 0, 4_000, 500, 1_200),
        Edit("a", 900, 4_000, 0, 500),
        Edit("a", 1_400, 3_000, 0, 200),
        Edit("b", 0, INFO.frames, 2_000, 3_200),
    )


def _fake_codecs(
    assets: dict[str, bytes],
    originals: dict[str, bytes],
    *,
    output_change: str | None = None,
    native_change: str | None = None,
) -> tuple[Decoder, Encoder, list[str], list[str]]:
    pcm_for_native = {native: originals[asset] for asset, native in assets.items()}
    comments_by_asset = {
        asset: parse_ogg_vorbis(native).comments for asset, native in assets.items()
    }
    decode_calls: list[str] = []
    encode_calls: list[str] = []
    rebuilt_natives: set[bytes] = set()

    def decoder(
        asset_id: str, native_path: Path, pcm_path: Path, info: PCMFormat
    ) -> None:
        decode_calls.append(asset_id)
        native = native_path.read_bytes()
        decoded = pcm_for_native.get(native)
        if decoded is None:
            raise ValueError("fake decoder has no source for Ogg fixture")
        if info != INFO:
            raise ValueError("fake decoder received unexpected PCM metadata")
        if output_change == "decoder-leak" and native in rebuilt_natives:
            leaked = bytearray(decoded)
            leaked[500 * info.frame_bytes : 501 * info.frame_bytes] = originals[
                asset_id
            ][500 * info.frame_bytes : 501 * info.frame_bytes]
            decoded = bytes(leaked)
        pcm_path.write_bytes(decoded)

    def encoder(
        asset_id: str, pcm_path: Path, native_path: Path, info: PCMFormat
    ) -> None:
        encode_calls.append(asset_id)
        edited = pcm_path.read_bytes()
        if info != INFO:
            raise ValueError("fake encoder received unexpected PCM metadata")
        output = bytearray(edited)
        if output_change == "not-silent" and asset_id == "b":
            struct.pack_into("<f", output, (2_500 * info.channels) * 4, 0.01)
        elif output_change == "requested-start" and asset_id == "a":
            output[500 * info.frame_bytes : 501 * info.frame_bytes] = originals[
                asset_id
            ][500 * info.frame_bytes : 501 * info.frame_bytes]
        elif output_change == "requested-end" and asset_id == "a":
            output[1_599 * info.frame_bytes : 1_600 * info.frame_bytes] = originals[
                asset_id
            ][1_599 * info.frame_bytes : 1_600 * info.frame_bytes]
        elif output_change == "outside-max-error" and asset_id == "a":
            for frame in range(100, 103):
                for channel in range(info.channels):
                    offset = (frame * info.channels + channel) * 4
                    sample = struct.unpack_from("<f", output, offset)[0]
                    struct.pack_into("<f", output, offset, sample + 0.06)
        elif output_change == "outside-snr" and asset_id == "a":
            assert output[436 * info.frame_bytes : 1_664 * info.frame_bytes] == bytes(
                (1_664 - 436) * info.frame_bytes
            )
            for frame in (*range(0, 372), *range(1_728, info.frames)):
                for channel in range(info.channels):
                    offset = (frame * info.channels + channel) * 4
                    sample = struct.unpack_from("<f", output, offset)[0]
                    struct.pack_into("<f", output, offset, sample + 0.03)
        native = build_ogg_fixture(
            frames=info.frames,
            comments=comments_by_asset[asset_id],
            vendor="fake libvorbis generation",
            nominal_bitrate=128_000,
            serial=0x1234 + len(encode_calls),
        )
        if native_change == "crc" and asset_id == "b":
            damaged = bytearray(native)
            damaged[-1] ^= 1
            native = bytes(damaged)
        pcm_for_native[native] = bytes(output)
        rebuilt_natives.add(native)
        native_path.write_bytes(native)

    return decoder, encoder, decode_calls, encode_calls


class _TamperingReader:
    def __init__(
        self,
        reader: Reader,
        mode: str,
        original: bytes,
        info: PCMFormat,
        tamper_frame: int = 500,
    ) -> None:
        self._reader = reader
        self._mode = mode
        self._original = original
        self.info = info
        self._tamper_frame = tamper_frame

    def blocks(self) -> Iterator[bytes]:
        pcm = bytearray(b"".join(self._reader.blocks()))
        if self._mode == "required frame":
            offset = self._tamper_frame * self.info.frame_bytes
            pcm[offset : offset + self.info.frame_bytes] = self._original[
                offset : offset + self.info.frame_bytes
            ]
        elif self._mode == "outside sample":
            pcm[2500 * self.info.frame_bytes] ^= 1
        elif self._mode == "frame count":
            pcm.extend(bytes(self.info.frame_bytes))
        block_bytes = 4096 * self.info.frame_bytes
        for offset in range(0, len(pcm), block_bytes):
            yield bytes(pcm[offset : offset + block_bytes])


class _TamperingStorage(WaveStorage):
    def __init__(
        self,
        mode: str,
        original: bytes,
        *,
        target_directory: str = "0",
        tamper_frame: int = 500,
    ) -> None:
        self.mode = mode
        self.original = original
        self.target_directory = target_directory
        self.tamper_frame = tamper_frame

    @contextmanager
    def open(self, path: Path) -> Iterator[Reader]:
        with super().open(path) as reader:
            if (
                path.name == "edited.pcmstore"
                and path.parent.parent.parent.name == self.target_directory
            ):
                yield _TamperingReader(
                    reader, self.mode, self.original, INFO, self.tamper_frame
                )
            else:
                yield reader


def test_prepare_groups_native_assets_uses_real_f32_scratch_and_keeps_atomicity(
    tmp_path: Path,
) -> None:
    assets, originals = _assets(tmp_path)
    before = _snapshot(tmp_path)
    decoder, encoder, decode_calls, encode_calls = _fake_codecs(assets, originals)

    staged = prepare_ogg(
        tmp_path,
        assets,
        originals,
        _edits(),
        decoder=decoder,
        encoder=encoder,
        info=INFO,
        quality=QUALITY,
    )

    assert set(staged) == {"a", "b"}
    assert Counter(encode_calls) == Counter({"a": 1, "b": 1})
    assert "untouched" not in encode_calls
    assert decode_calls.count("a") == 2
    assert decode_calls.count("b") == 2
    expected = {
        "a": _silenced(originals["a"], [(436, 1_664)]),
        "b": _silenced(originals["b"], [(1_936, 3_264)]),
    }
    for asset, native in staged.items():
        parsed = parse_ogg_vorbis(native, expected_frames=INFO.frames)
        assert parsed.vendor == "fake libvorbis generation"
        assert staged[asset] != assets[asset]
        decoded = _pcm_for_fake_native(native, assets, originals, encode_calls)
        assert decoded == expected[asset]
    assert _snapshot(tmp_path) == before
    assert not list(tmp_path.glob("native-prepare-*"))


def _pcm_for_fake_native(
    native: bytes,
    assets: dict[str, bytes],
    originals: dict[str, bytes],
    encode_calls: list[str],
) -> bytes:
    del encode_calls
    # The fake encoder's generated comment carries the asset-specific tag.
    info = parse_ogg_vorbis(native)
    asset = dict(info.comments).get("ASSET")
    assert asset in assets
    source_pcm = originals[asset]
    if asset == "a":
        return _silenced(source_pcm, [(436, 1_664)])
    return _silenced(source_pcm, [(1_936, 3_264)])


@pytest.mark.parametrize("failing_asset_first", [False, True])
def test_extraction_failure_is_atomic_in_both_asset_orders(
    tmp_path: Path, failing_asset_first: bool
) -> None:
    assets, originals = _assets(tmp_path)
    decoder, encoder, decode_calls, encode_calls = _fake_codecs(assets, originals)
    normal_decoder = decoder

    def fail_b(
        asset_id: str, native_path: Path, pcm_path: Path, info: PCMFormat
    ) -> None:
        if asset_id == "b" and native_path.name == "source.ogg":
            decode_calls.append(asset_id)
            raise OSError("injected Vorbis extraction failure")
        normal_decoder(asset_id, native_path, pcm_path, info)

    edits = tuple(reversed(_edits())) if failing_asset_first else _edits()
    before = _snapshot(tmp_path)
    with pytest.raises(ExtractionError) as error:
        prepare_ogg(
            tmp_path,
            assets,
            originals,
            edits,
            decoder=fail_b,
            encoder=encoder,
            info=INFO,
            quality=QUALITY,
        )
    assert (
        str(error.value)
        == "required asset b: extraction: injected Vorbis extraction failure"
    )
    assert error.value.asset_id == "b"
    assert decode_calls == (["b"] if failing_asset_first else ["a", "a", "b"])
    assert encode_calls == ([] if failing_asset_first else ["a"])
    assert _snapshot(tmp_path) == before
    assert not list(tmp_path.glob("native-prepare-*"))


@pytest.mark.parametrize("failing_asset_first", [False, True])
@pytest.mark.parametrize("failure", ["corrupt", "unsupported", "encode"])
def test_corrupt_unsupported_and_encode_failures_refuse_whole_request_in_both_orders(
    tmp_path: Path, failing_asset_first: bool, failure: str
) -> None:
    assets, originals = _assets(tmp_path)
    decoder, normal_encoder, _, encode_calls = _fake_codecs(assets, originals)
    requested_edits = _edits()
    if failing_asset_first:
        requested_edits = tuple(reversed(requested_edits))

    error_type: type[NativeStageError]
    detail: str
    failing_encoder = normal_encoder
    if failure == "corrupt":
        damaged = bytearray(assets["b"])
        damaged[-1] ^= 1
        assets["b"] = bytes(damaged)
        error_type = NativeValidationError
        detail = "Ogg page CRC mismatch"
    elif failure == "unsupported":
        assets["b"] = build_ogg_fixture(frames=INFO.frames, channels=6)
        error_type = NativeValidationError
        detail = "unsupported Vorbis channel profile"
    else:
        expected_b = _silenced(originals["b"], [(1_936, 3_264)])

        def fail_encoder(
            asset_id: str,
            pcm_path: Path,
            native_path: Path,
            info: PCMFormat,
        ) -> None:
            if asset_id == "b":
                encode_calls.append(asset_id)
                assert pcm_path.is_file()
                assert pcm_path.read_bytes() == expected_b
                raise OSError("injected libvorbis encode failure")
            normal_encoder(asset_id, pcm_path, native_path, info)

        failing_encoder = fail_encoder
        error_type = ReconstructionError
        detail = "injected libvorbis encode failure"

    before = _snapshot(tmp_path)
    with pytest.raises(error_type) as error:
        prepare_ogg(
            tmp_path,
            assets,
            originals,
            requested_edits,
            decoder=decoder,
            encoder=failing_encoder,
            info=INFO,
            quality=QUALITY,
        )
    assert type(error.value) is error_type
    assert error.value.asset_id == "b"
    assert error.value.detail == detail
    assert str(error.value) == f"required asset b: {error_type.stage}: {detail}"
    assert _snapshot(tmp_path) == before
    assert not list(tmp_path.glob("native-prepare-*"))
    if failure == "encode" and failing_asset_first:
        assert encode_calls == ["b"]
    if failure == "encode" and not failing_asset_first:
        assert encode_calls == ["a", "b"]
    if failure in ("corrupt", "unsupported") and failing_asset_first:
        assert encode_calls == []
    if failure in ("corrupt", "unsupported") and not failing_asset_first:
        assert encode_calls == ["a"]


@pytest.mark.parametrize(
    ("mode", "detail"),
    [
        ("required frame", "required edit incomplete"),
        ("outside sample", "unaffected frames changed"),
        ("frame count", "frame count changed"),
    ],
)
def test_intermediate_edit_completeness_refusal_is_atomic(
    tmp_path: Path, mode: str, detail: str
) -> None:
    assets, originals = _assets(tmp_path)
    decoder, encoder, _, encode_calls = _fake_codecs(assets, originals)
    before = _snapshot(tmp_path)
    with pytest.raises(EditError, match=detail):
        prepare_ogg(
            tmp_path,
            assets,
            originals,
            _edits(),
            decoder=decoder,
            encoder=encoder,
            info=INFO,
            storage=_TamperingStorage(mode, originals["a"]),
            quality=QUALITY,
        )
    assert encode_calls == []
    assert _snapshot(tmp_path) == before


def test_padded_intermediate_frames_are_checked_before_encoding(
    tmp_path: Path,
) -> None:
    assets, originals = _assets(tmp_path)
    decoder, encoder, _, encode_calls = _fake_codecs(assets, originals)
    before = _snapshot(tmp_path)
    with pytest.raises(EditError, match="required edit incomplete"):
        prepare_ogg(
            tmp_path,
            assets,
            originals,
            _edits(),
            decoder=decoder,
            encoder=encoder,
            info=INFO,
            storage=_TamperingStorage(
                "required frame",
                originals["a"],
                target_directory="0",
                tamper_frame=450,
            ),
            quality=QUALITY,
        )
    assert encode_calls == []
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("failing_asset_first", [False, True])
def test_edit_completeness_failure_is_atomic_in_both_asset_orders(
    tmp_path: Path, failing_asset_first: bool
) -> None:
    assets, originals = _assets(tmp_path)
    decoder, encoder, _, encode_calls = _fake_codecs(assets, originals)
    target_directory = "0" if failing_asset_first else "1"
    storage = _TamperingStorage(
        "required frame",
        originals["b"],
        target_directory=target_directory,
        tamper_frame=2_000,
    )
    edits = tuple(reversed(_edits())) if failing_asset_first else _edits()
    before = _snapshot(tmp_path)
    with pytest.raises(EditError) as error:
        prepare_ogg(
            tmp_path,
            assets,
            originals,
            edits,
            decoder=decoder,
            encoder=encoder,
            info=INFO,
            storage=storage,
            quality=QUALITY,
        )
    assert str(error.value) == "required asset b: PCM edit: required edit incomplete"
    assert error.value.asset_id == "b"
    assert encode_calls == ([] if failing_asset_first else ["a"])
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("mode", ["not-silent", "outside-max-error"])
def test_lossy_decode_tolerance_violation_refuses_rebuild_atomically(
    tmp_path: Path, mode: str
) -> None:
    assets, originals = _assets(tmp_path)
    decoder, encoder, _, encode_calls = _fake_codecs(
        assets, originals, output_change=mode
    )
    before = _snapshot(tmp_path)
    with pytest.raises(ReconstructionError) as error:
        prepare_ogg(
            tmp_path,
            assets,
            originals,
            _edits(),
            decoder=decoder,
            encoder=encoder,
            info=INFO,
            quality=QUALITY,
        )
    assert error.value.asset_id == ("b" if mode == "not-silent" else "a")
    assert "reconstruction" in str(error.value)
    assert encode_calls
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("mode", ["requested-start", "requested-end"])
def test_rebuilt_audio_restored_at_requested_range_edges_is_refused(
    tmp_path: Path, mode: str
) -> None:
    assets, originals = _assets(tmp_path)
    decoder, encoder, _, encode_calls = _fake_codecs(
        assets, originals, output_change=mode
    )
    with pytest.raises(ReconstructionError) as error:
        prepare_ogg(
            tmp_path,
            assets,
            originals,
            _edits(),
            decoder=decoder,
            encoder=encoder,
            info=INFO,
            quality=QUALITY,
        )
    assert error.value.asset_id == "a"
    assert "requested-range silence peak" in error.value.detail
    assert encode_calls == ["a"]


def test_unpadded_decoder_leak_in_requested_range_is_refused(
    tmp_path: Path,
) -> None:
    assets, originals = _assets(tmp_path)
    decoder, encoder, _, encode_calls = _fake_codecs(
        assets, originals, output_change="decoder-leak"
    )
    with pytest.raises(ReconstructionError) as error:
        prepare_ogg(
            tmp_path,
            assets,
            originals,
            _edits(),
            decoder=decoder,
            encoder=encoder,
            info=INFO,
            quality=QUALITY,
        )
    assert error.value.asset_id == "a"
    assert "requested-range silence peak" in error.value.detail
    assert encode_calls == ["a"]


def test_padded_ranges_merge_touch_and_clamp_to_clip_edges() -> None:
    assert _padded_ranges([(0, 10), (10, 20), (90, 100)], frames=100, padding=5) == [
        (0, 25),
        (85, 100),
    ]


def test_padded_reconstruction_with_silent_requested_range_passes() -> None:
    original = _pcm(0)
    padded = _silenced(original, [(436, 1_664)])
    verify_lossy_reconstruction(
        "padded",
        original,
        padded,
        padded,
        [(436, 1_664)],
        INFO,
        policy=QUALITY,
        requested_ranges=[(500, 1_600)],
    )


@pytest.mark.parametrize("failing_asset_first", [False, True])
def test_rebuilt_native_validation_failure_is_atomic_in_both_asset_orders(
    tmp_path: Path, failing_asset_first: bool
) -> None:
    assets, originals = _assets(tmp_path)
    decoder, encoder, decode_calls, encode_calls = _fake_codecs(
        assets, originals, native_change="crc"
    )
    edits = tuple(reversed(_edits())) if failing_asset_first else _edits()
    before = _snapshot(tmp_path)
    with pytest.raises(ReconstructionError) as error:
        prepare_ogg(
            tmp_path,
            assets,
            originals,
            edits,
            decoder=decoder,
            encoder=encoder,
            info=INFO,
            quality=QUALITY,
        )
    assert str(error.value) == "required asset b: reconstruction: Ogg page CRC mismatch"
    assert error.value.asset_id == "b"
    assert decode_calls.count("b") == 1
    assert encode_calls == (["b"] if failing_asset_first else ["a", "b"])
    assert _snapshot(tmp_path) == before
    assert not list(tmp_path.glob("native-prepare-*"))


def test_lossy_snr_gate_refuses_broad_low_amplitude_outside_perturbation(
    tmp_path: Path,
) -> None:
    assets, originals = _assets(tmp_path)
    simulated = bytearray(_silenced(originals["a"], [(436, 1_664)]))
    for frame in (*range(0, 372), *range(1_728, INFO.frames)):
        for channel in range(INFO.channels):
            offset = (frame * INFO.channels + channel) * 4
            sample = struct.unpack_from("<f", simulated, offset)[0]
            struct.pack_into("<f", simulated, offset, sample + 0.03)
    metrics = measure_lossy_effects(
        originals["a"],
        bytes(simulated),
        [(436, 1_664)],
        INFO,
        policy=QUALITY,
        requested_ranges=[(500, 1_600)],
    )
    assert 13.0 <= metrics.outside_regions[0].snr_db <= 14.0
    assert metrics.outside_regions[0].maximum_absolute_error < 0.05
    decoder, encoder, _, encode_calls = _fake_codecs(
        assets, originals, output_change="outside-snr"
    )
    before = _snapshot(tmp_path)
    with pytest.raises(ReconstructionError) as error:
        prepare_ogg(
            tmp_path,
            assets,
            originals,
            _edits(),
            decoder=decoder,
            encoder=encoder,
            info=INFO,
            quality=QUALITY,
        )
    assert error.value.asset_id == "a"
    assert "SNR" in error.value.detail
    assert "unaffected-region" in error.value.detail
    assert "peak error" not in error.value.detail
    assert QUALITY.maximum_outside_abs_error == 0.05
    assert encode_calls == ["a"]
    assert _snapshot(tmp_path) == before


def test_lossy_max_error_gate_refuses_when_snr_is_acceptable(
    tmp_path: Path,
) -> None:
    assets, originals = _assets(tmp_path)
    simulated = bytearray(_silenced(originals["a"], [(436, 1_664)]))
    for frame in range(100, 103):
        for channel in range(INFO.channels):
            offset = (frame * INFO.channels + channel) * 4
            sample = struct.unpack_from("<f", simulated, offset)[0]
            struct.pack_into("<f", simulated, offset, sample + 0.06)
    metrics = measure_lossy_effects(
        originals["a"],
        bytes(simulated),
        [(436, 1_664)],
        INFO,
        policy=QUALITY,
        requested_ranges=[(500, 1_600)],
    )
    assert 27.0 <= metrics.outside_regions[0].snr_db <= 30.0
    assert 0.05 < metrics.outside_regions[0].maximum_absolute_error < 0.07
    decoder, encoder, _, encode_calls = _fake_codecs(
        assets, originals, output_change="outside-max-error"
    )
    with pytest.raises(ReconstructionError) as error:
        prepare_ogg(
            tmp_path,
            assets,
            originals,
            _edits(),
            decoder=decoder,
            encoder=encoder,
            info=INFO,
            quality=QUALITY,
        )
    assert error.value.asset_id == "a"
    assert "peak error" in error.value.detail
    assert "SNR" not in error.value.detail
    assert encode_calls == ["a"]


@pytest.mark.parametrize(
    ("offset", "expected_detail"),
    [
        (0.06, "unaffected guard-region 0 peak error"),
        (0.03, "unaffected guard-region 0 SNR"),
    ],
)
def test_guard_quality_gates_refuse_independently(
    offset: float, expected_detail: str
) -> None:
    original = _pcm(0)
    padded_ranges = [(0, 1_264)]
    requested_ranges = [(0, 1_200)]
    decoded = bytearray(_silenced(original, padded_ranges))
    for frame in range(1_264, 1_328):
        if offset == 0.06 and frame != 1_270:
            continue
        for channel in range(INFO.channels):
            sample_offset = (frame * INFO.channels + channel) * 4
            sample = struct.unpack_from("<f", decoded, sample_offset)[0]
            struct.pack_into("<f", decoded, sample_offset, sample + offset)
    decoded_pcm = bytes(decoded)
    metrics = measure_lossy_effects(
        original,
        decoded_pcm,
        padded_ranges,
        INFO,
        policy=QUALITY,
        requested_ranges=requested_ranges,
    )
    guard = metrics.guard_regions[0]
    if offset == 0.06:
        assert guard.maximum_absolute_error > QUALITY.maximum_guard_abs_error
        assert guard.snr_db > QUALITY.minimum_guard_snr_db
    else:
        assert guard.maximum_absolute_error < QUALITY.maximum_guard_abs_error
        assert guard.snr_db < QUALITY.minimum_guard_snr_db
    with pytest.raises(ValueError, match=expected_detail):
        verify_lossy_reconstruction(
            "guard-gate",
            original,
            _silenced(original, padded_ranges),
            decoded_pcm,
            padded_ranges,
            INFO,
            policy=QUALITY,
            requested_ranges=requested_ranges,
        )


def test_guard_regions_merge_normalize_and_do_not_duplicate_ranges() -> None:
    assert _guard_regions(100, [(20, 30), (29, 40), (40, 45)], 10) == [
        (10, 20),
        (45, 55),
    ]


@pytest.mark.parametrize(
    "ranges",
    [
        [(-1, 1)],
        [(INFO.frames - 1, INFO.frames + 1)],
        [(4, 3)],
        [(4, 4)],
        [(1.0, 2)],
    ],
)
def test_lossy_verifier_rejects_invalid_edit_ranges(
    ranges: list[tuple[int, int]],
) -> None:
    pcm = _pcm(0)
    with pytest.raises(ValueError, match="invalid edit frame range"):
        verify_lossy_reconstruction(
            "invalid-range",
            pcm,
            pcm,
            pcm,
            ranges,
            INFO,
            policy=QUALITY,
        )


def test_guard_region_catches_all_zero_output_when_expanded_guards_cover_clip() -> None:
    original = b"".join(
        struct.pack(
            "<ff",
            0.22 * math.sin(frame * 0.037),
            0.18 * math.cos(frame * 0.031),
        )
        for frame in range(PRODUCTION_INFO.frames)
    )
    decoded_silence = bytes(len(original))
    with pytest.raises(ValueError, match="unaffected guard-region"):
        verify_lossy_reconstruction(
            "guarded",
            original,
            decoded_silence,
            decoded_silence,
            [(2_048, 64_102)],
            PRODUCTION_INFO,
        )


def test_full_clip_edit_can_pass_without_unedited_frames_to_verify() -> None:
    original = _pcm(0)
    silence = bytes(len(original))
    verify_lossy_reconstruction(
        "whole-clip",
        original,
        silence,
        silence,
        [(0, INFO.frames)],
        INFO,
        policy=QUALITY,
    )


def test_source_without_nominal_bitrate_is_refused_before_decode(
    tmp_path: Path,
) -> None:
    assets, originals = _assets(tmp_path)
    assets["a"] = build_ogg_fixture(
        frames=INFO.frames,
        comments=parse_ogg_vorbis(assets["a"]).comments,
        nominal_bitrate=-1,
    )
    decoder, encoder, decode_calls, encode_calls = _fake_codecs(assets, originals)
    before = _snapshot(tmp_path)
    with pytest.raises(NativeValidationError) as error:
        prepare_ogg(
            tmp_path,
            assets,
            originals,
            _edits(),
            decoder=decoder,
            encoder=encoder,
            info=INFO,
            quality=QUALITY,
        )
    assert error.value.asset_id == "a"
    assert "nominal bitrate is absent" in str(error.value)
    assert decode_calls == []
    assert encode_calls == []
    assert _snapshot(tmp_path) == before


def test_frame_boundary_mapping_is_exact_for_every_fixture_frame() -> None:
    for frame in range(INFO.frames + 1):
        start = frame_boundary_seconds(frame, INFO.rate, INFO.frames, "start")
        assert math.floor(start * INFO.rate) == frame
        end = frame_boundary_seconds(frame, INFO.rate, INFO.frames, "end")
        if frame == INFO.frames:
            assert end == INFO.frames / INFO.rate
        else:
            assert math.ceil(end * INFO.rate) == frame
