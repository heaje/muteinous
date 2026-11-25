import math
import struct
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
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
)
from experiments.native_ogg.ogg_core import (
    build_ogg_fixture,
    parse_ogg_vorbis,
)
from experiments.native_ogg.ogg_prepare import (
    QualityPolicy,
    prepare_ogg,
)
from muteinous.core.audio.pcm import Curve, PCMFormat
from muteinous.core.audio.scratch import Scratch
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
    failure: str | None = None,
) -> tuple[Decoder, Encoder, list[str], dict[bytes, bytes]]:
    pcm_for_native = {native: originals[asset] for asset, native in assets.items()}
    comments_by_asset = {
        asset: parse_ogg_vorbis(native).comments for asset, native in assets.items()
    }
    encode_calls: list[str] = []

    def decoder(
        asset_id: str, native_path: Path, pcm_path: Path, info: PCMFormat
    ) -> None:
        native = native_path.read_bytes()
        decoded = pcm_for_native[native]
        pcm_path.write_bytes(decoded)

    def encoder(
        asset_id: str, pcm_path: Path, native_path: Path, info: PCMFormat
    ) -> None:
        encode_calls.append(asset_id)

        output = pcm_path.read_bytes()
        native = build_ogg_fixture(
            frames=info.frames,
            comments=comments_by_asset[asset_id],
            vendor="fake libvorbis generation",
            nominal_bitrate=128_000,
            serial=0x1234 + len(encode_calls),
        )
        if failure == "rebuilt native validation" and asset_id == "b":
            damaged = bytearray(native)
            damaged[-1] ^= 1
            native = bytes(damaged)
        pcm_for_native[native] = output
        native_path.write_bytes(native)

    return decoder, encoder, encode_calls, pcm_for_native


class _TamperingReader:
    def __init__(self, reader: Reader, mode: str, original: bytes) -> None:
        self._reader = reader
        self._mode = mode
        self._original = original
        self.info = reader.info

    def blocks(self) -> Iterator[bytes]:
        pcm = bytearray(b"".join(self._reader.blocks()))
        if self._mode == "required frame":
            offset = 500 * self.info.frame_bytes
            pcm[offset : offset + self.info.frame_bytes] = self._original[
                offset : offset + self.info.frame_bytes
            ]
        elif self._mode == "extra muted frame":
            offset = 435 * self.info.frame_bytes
            pcm[offset : offset + self.info.frame_bytes] = bytes(self.info.frame_bytes)

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
            if path.name == "edited.pcmstore" and path.parent.parent.parent.name == "0":
                yield _TamperingReader(reader, self.mode, self.original)
            else:
                yield reader


def _assert_atomic_failure(
    root: Path,
    assets: dict[str, bytes],
    originals: dict[str, bytes],
    edits: Sequence[Edit],
    decoder: Decoder,
    encoder: Encoder,
    error_type: type[NativeStageError],
    *,
    expected_asset: str = "b",
    storage: WaveStorage | None = None,
    quality: QualityPolicy = QUALITY,
) -> None:
    before = _snapshot(root)
    with pytest.raises(error_type) as error:
        prepare_ogg(
            root,
            assets,
            originals,
            edits,
            decoder=decoder,
            encoder=encoder,
            info=INFO,
            storage=storage,
            quality=quality,
        )
    assert type(error.value) is error_type
    assert error.value.asset_id == expected_asset
    assert _snapshot(root) == before
    assert not list(root.glob("native-prepare-*"))


def test_prepare_merges_edits_pads_and_rebuilds_each_affected_asset_once(
    tmp_path: Path,
) -> None:
    assets, originals = _assets(tmp_path)
    before = _snapshot(tmp_path)
    decoder, encoder, encode_calls, pcm_for_native = _fake_codecs(assets, originals)

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
    expected = {
        "a": _silenced(originals["a"], [(436, 1_664)]),
        "b": _silenced(originals["b"], [(1_936, 3_264)]),
    }
    for asset, native in staged.items():
        parse_ogg_vorbis(native, expected_frames=INFO.frames)
        assert pcm_for_native[native] == expected[asset]
    assert _snapshot(tmp_path) == before
    assert not list(tmp_path.glob("native-prepare-*"))


def test_padding_is_clamped_to_interior_segment_and_neighbors_stay_bit_exact(
    tmp_path: Path,
) -> None:
    assets, originals = _assets(tmp_path)
    decoder, encoder, _, pcm_for_native = _fake_codecs(assets, originals)
    edits = (Edit("a", 1_000, 1_000, 0, 1_000),)

    staged = prepare_ogg(
        tmp_path,
        assets,
        originals,
        edits,
        decoder=decoder,
        encoder=encoder,
        info=INFO,
        quality=QUALITY,
    )

    output = pcm_for_native[staged["a"]]
    expected = _silenced(originals["a"], [(1_000, 2_000)])
    assert output == expected
    assert (
        output[: 1_000 * INFO.frame_bytes] == originals["a"][: 1_000 * INFO.frame_bytes]
    )
    assert (
        output[2_000 * INFO.frame_bytes :] == originals["a"][2_000 * INFO.frame_bytes :]
    )


def test_segment_bounded_padding_refuses_requested_edge_leakage(
    tmp_path: Path,
) -> None:
    assets, originals = _assets(tmp_path)
    base_decoder, encoder, _, _ = _fake_codecs(assets, originals)
    edits = (Edit("a", 1_000, 1_000, 0, 100),)
    before = _snapshot(tmp_path)

    def leaking_decoder(
        asset_id: str, native_path: Path, pcm_path: Path, info: PCMFormat
    ) -> None:
        base_decoder(asset_id, native_path, pcm_path, info)
        if native_path.name == "rebuilt.ogg":
            decoded = bytearray(pcm_path.read_bytes())
            start = 1_000 * info.frame_bytes
            end = start + info.frame_bytes
            decoded[start:end] = originals[asset_id][start:end]
            pcm_path.write_bytes(decoded)

    with pytest.raises(ReconstructionError) as error:
        prepare_ogg(
            tmp_path,
            assets,
            originals,
            edits,
            decoder=leaking_decoder,
            encoder=encoder,
            info=INFO,
            quality=QUALITY,
        )

    assert type(error.value) is ReconstructionError
    assert error.value.asset_id == "a"
    assert _snapshot(tmp_path) == before
    assert not list(tmp_path.glob("native-prepare-*"))


@pytest.mark.parametrize(
    "mode",
    ["required frame", "extra muted frame"],
)
def test_padded_edit_completeness_verifier_rejects_tampering_before_encode(
    tmp_path: Path, mode: str
) -> None:
    assets, originals = _assets(tmp_path)
    decoder, encoder, _, _ = _fake_codecs(assets, originals)

    _assert_atomic_failure(
        tmp_path,
        assets,
        originals,
        _edits(),
        decoder,
        encoder,
        EditError,
        expected_asset="a",
        storage=_TamperingStorage(mode, originals["a"]),
    )


@pytest.mark.parametrize(
    "failure",
    [
        "source CRC validation",
        "source profile validation",
        "extraction mismatch",
        "shared editor failure",
        "rebuilt native validation",
    ],
)
@pytest.mark.parametrize("failing_asset_first", [False, True])
def test_all_preparation_stages_refuse_atomically_in_either_asset_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    failing_asset_first: bool,
) -> None:
    assets, originals = _assets(tmp_path)
    decoder, encoder, _, _ = _fake_codecs(assets, originals, failure=failure)
    if failure == "source CRC validation":
        damaged = bytearray(assets["b"])
        damaged[-1] ^= 1
        assets["b"] = bytes(damaged)
    elif failure == "source profile validation":
        assets["b"] = build_ogg_fixture(frames=INFO.frames, channels=6)

    if failure == "extraction mismatch":
        source_decoder = decoder

        def mismatching_decoder(
            asset_id: str, native_path: Path, pcm_path: Path, info: PCMFormat
        ) -> None:
            source_decoder(asset_id, native_path, pcm_path, info)
            if asset_id == "b" and native_path.name == "source.ogg":
                pcm = bytearray(pcm_path.read_bytes())
                pcm[0] ^= 1
                pcm_path.write_bytes(pcm)

        decoder = mismatching_decoder

    error_types: dict[str, type[NativeStageError]] = {
        "source CRC validation": NativeValidationError,
        "source profile validation": NativeValidationError,
        "extraction mismatch": ExtractionError,
        "shared editor failure": EditError,
        "rebuilt native validation": ReconstructionError,
    }
    call_number = 0
    real_edit = Scratch.edit

    def failing_edit(
        self: Scratch,
        ranges: Iterable[tuple[float, float]],
        *,
        before: float = 0,
        after: float = 0,
        fade: float = 0,
        curve: Curve = "cosine",
    ) -> Path:
        nonlocal call_number
        call_number += 1
        target_call = 1 if failing_asset_first else 2
        if failure == "shared editor failure" and call_number == target_call:
            raise OSError("injected PCM editor failure")
        return real_edit(
            self, ranges, before=before, after=after, fade=fade, curve=curve
        )

    monkeypatch.setattr(Scratch, "edit", failing_edit)
    edits = tuple(reversed(_edits())) if failing_asset_first else _edits()
    _assert_atomic_failure(
        tmp_path,
        assets,
        originals,
        edits,
        decoder,
        encoder,
        error_types[failure],
    )
