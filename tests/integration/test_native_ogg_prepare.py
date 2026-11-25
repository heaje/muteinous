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
    NativeStageError,
    NativeValidationError,
    ReconstructionError,
    frame_boundary_seconds,
)
from experiments.native_ogg.ogg_core import build_ogg_fixture, parse_ogg_vorbis
from experiments.native_ogg.ogg_prepare import (
    QualityPolicy,
    prepare_ogg,
)
from muteinous.core.audio.pcm import PCMFormat
from muteinous.core.audio.storage import Reader
from muteinous.core.audio.wav import WaveStorage

pytestmark = pytest.mark.portable

INFO = PCMFormat(44_100, 2, "f32", 5_000, 3)
QUALITY = QualityPolicy(
    guard_frames=64,
    silence_peak_limit=0.001,
    minimum_outside_snr_db=24.0,
    maximum_outside_abs_error=0.08,
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
) -> tuple[Decoder, Encoder, list[str], list[str]]:
    pcm_for_native = {native: originals[asset] for asset, native in assets.items()}
    comments_by_asset = {
        asset: parse_ogg_vorbis(native).comments for asset, native in assets.items()
    }
    decode_calls: list[str] = []
    encode_calls: list[str] = []

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
        elif output_change == "outside-tolerance" and asset_id == "a":
            struct.pack_into("<f", output, 0, 0.12)
        native = build_ogg_fixture(
            frames=info.frames,
            comments=comments_by_asset[asset_id],
            vendor="fake libvorbis generation",
            nominal_bitrate=128_000,
            serial=0x1234 + len(encode_calls),
        )
        pcm_for_native[native] = bytes(output)
        native_path.write_bytes(native)

    return decoder, encoder, decode_calls, encode_calls


class _TamperingReader:
    def __init__(
        self, reader: Reader, mode: str, original: bytes, info: PCMFormat
    ) -> None:
        self._reader = reader
        self._mode = mode
        self._original = original
        self.info = info

    def blocks(self) -> Iterator[bytes]:
        pcm = bytearray(b"".join(self._reader.blocks()))
        if self._mode == "required frame":
            offset = 500 * self.info.frame_bytes
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
    def __init__(self, mode: str, original: bytes) -> None:
        self.mode = mode
        self.original = original

    @contextmanager
    def open(self, path: Path) -> Iterator[Reader]:
        with super().open(path) as reader:
            if path.name == "edited.pcmstore":
                yield _TamperingReader(reader, self.mode, self.original, INFO)
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
        "a": _silenced(originals["a"], [(500, 1_600)]),
        "b": _silenced(originals["b"], [(2_000, 3_200)]),
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
        return _silenced(source_pcm, [(500, 1_600)])
    return _silenced(source_pcm, [(2_000, 3_200)])


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
        expected_b = _silenced(originals["b"], [(2_000, 3_200)])

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
    assert detail in str(error.value)
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


@pytest.mark.parametrize("mode", ["not-silent", "outside-tolerance"])
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
    assert error.value.asset_id == ("a" if mode == "outside-tolerance" else "b")
    assert "reconstruction" in str(error.value)
    assert encode_calls
    assert _snapshot(tmp_path) == before


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
