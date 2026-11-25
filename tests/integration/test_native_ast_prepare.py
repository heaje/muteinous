import struct
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

import pytest

from experiments.native_ast import ast_core
from experiments.native_ast.ast_core import (
    FRAMES,
    INFO,
    Decoder,
    Edit,
    EditError,
    Encoder,
    ExtractionError,
    NativeStageError,
    NativeValidationError,
    ReconstructionError,
    build_canonical_ast,
    frame_boundary_seconds,
    prepare,
    validate_fixture,
)
from muteinous.core.audio.pcm import Curve, PCMFormat
from muteinous.core.audio.scratch import Scratch, audio_scratch
from muteinous.core.audio.storage import Reader
from muteinous.core.audio.wav import WaveStorage

pytestmark = pytest.mark.portable


class RecordingWaveStorage(WaveStorage):
    def __init__(self) -> None:
        self.read_infos: list[PCMFormat] = []

    @contextmanager
    def open(self, path: Path) -> Iterator[Reader]:
        with super().open(path) as reader:
            self.read_infos.append(reader.info)
            yield reader


class _TamperingReader:
    def __init__(
        self,
        reader: Reader,
        mode: str,
        original: bytes,
        info: PCMFormat,
        tamper_frame: int = 1001,
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
        elif self._mode == "extra muted frame":
            offset = 1000 * self.info.frame_bytes
            pcm[offset : offset + self.info.frame_bytes] = bytes(self.info.frame_bytes)
        elif self._mode == "outside sample":
            pcm[1300 * self.info.frame_bytes] ^= 1
        elif self._mode == "frame count":
            pcm.extend(bytes(self.info.frame_bytes))

        block_bytes = 4096 * self.info.frame_bytes
        for offset in range(0, len(pcm), block_bytes):
            yield bytes(pcm[offset : offset + block_bytes])


class TamperingWaveStorage(WaveStorage):
    def __init__(
        self,
        mode: str,
        original: bytes,
        info: PCMFormat,
        *,
        target_directory: str = "0",
        tamper_frame: int = 1001,
    ) -> None:
        self.mode = mode
        self.original = original
        self.info = info
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
                    reader,
                    self.mode,
                    self.original,
                    self.info,
                    self.tamper_frame,
                )
            else:
                yield reader


class _SourceMutatingReader:
    def __init__(self, reader: Reader, source_path: Path) -> None:
        self._reader = reader
        self._source_path = source_path
        self.info = reader.info

    def blocks(self) -> Iterator[bytes]:
        yield from self._reader.blocks()
        self._source_path.write_bytes(b"source changed during edit")


class SourceMutatingWaveStorage(WaveStorage):
    @contextmanager
    def open(self, path: Path) -> Iterator[Reader]:
        with super().open(path) as reader:
            if path.name == "edited.pcmstore":
                private_asset = path.parent.parent.parent
                source_path = private_asset / "source.ast"
                yield _SourceMutatingReader(reader, source_path)
            else:
                yield reader


def _pcm(seed: int) -> bytes:
    return b"".join(
        struct.pack(
            "<hh",
            (frame * 67 + seed) % 65_536 - 32_768,
            32_767 - (frame * 137 + seed) % 65_536,
        )
        for frame in range(FRAMES)
    )


def _expected_edit(pcm: bytes, ranges: Sequence[tuple[int, int]]) -> bytes:
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
        asset: _pcm(seed) for asset, seed in (("a", 0), ("b", 19), ("untouched", 31))
    }
    assets: dict[str, bytes] = {}
    for asset, pcm in originals.items():
        native = build_canonical_ast(pcm, INFO)
        validate_fixture(native, pcm, asset_id=asset)
        assets[asset] = native
        (root / f"{asset}.ast").write_bytes(native)
    return assets, originals


def _edits() -> tuple[Edit, ...]:
    return (
        Edit("a", 0, 4096, 1001, 1080),
        Edit("a", 1040, 2048, 40, 120),
        Edit("a", 1100, 2048, 30, 157),
        Edit("a", 4000, 1024, 0, 50),
        Edit("b", 0, 4096, 2048, 2176),
    )


def _fake_codecs(
    assets: dict[str, bytes], originals: dict[str, bytes]
) -> tuple[Decoder, Encoder, list[str], list[str]]:
    pcm_for_native = {native: originals[asset] for asset, native in assets.items()}
    decode_calls: list[str] = []
    encode_calls: list[str] = []

    def decoder(
        asset_id: str, native_path: Path, pcm_path: Path, info: PCMFormat
    ) -> None:
        decode_calls.append(asset_id)
        native = native_path.read_bytes()
        pcm = pcm_for_native[native]
        pcm_path.write_bytes(pcm)

    def encoder(
        asset_id: str, pcm_path: Path, native_path: Path, info: PCMFormat
    ) -> None:
        encode_calls.append(asset_id)
        pcm = pcm_path.read_bytes()
        native = build_canonical_ast(pcm, info)
        validate_fixture(native, pcm, asset_id=asset_id, info=info)
        pcm_for_native[native] = pcm
        native_path.write_bytes(native)

    return decoder, encoder, decode_calls, encode_calls


def _assert_atomic_failure(
    root: Path,
    assets: dict[str, bytes],
    originals: dict[str, bytes],
    edits: Sequence[Edit],
    decoder: Decoder,
    encoder: Encoder,
    error_type: type[NativeStageError],
    message: str,
    *,
    storage: WaveStorage | None = None,
) -> NativeStageError:
    before = _snapshot(root)
    with pytest.raises(error_type) as error:
        prepare(
            root,
            assets,
            originals,
            edits,
            decoder=decoder,
            encoder=encoder,
            storage=storage or WaveStorage(),
        )
    assert type(error.value) is error_type
    assert str(error.value) == message
    assert error.value.asset_id in str(error.value)
    assert _snapshot(root) == before
    return error.value


def test_prepare_uses_actual_shared_pcm_and_rebuilds_each_affected_asset_once(
    tmp_path: Path,
) -> None:
    assets, originals = _assets(tmp_path)
    before = _snapshot(tmp_path)
    decoder, encoder, _, encode_calls = _fake_codecs(assets, originals)
    storage = RecordingWaveStorage()

    staged = prepare(
        tmp_path,
        assets,
        originals,
        _edits(),
        decoder=decoder,
        encoder=encoder,
        storage=storage,
    )

    assert set(staged) == {"a", "b"}
    assert Counter(encode_calls) == Counter({"a": 1, "b": 1})
    assert "untouched" not in encode_calls
    assert all(info.channel_mask == 3 for info in storage.read_infos)
    assert INFO == PCMFormat(32_000, 2, "s16", FRAMES, 3)

    expected = {
        "a": _expected_edit(originals["a"], [(1001, 1257), (4000, 4050)]),
        "b": _expected_edit(originals["b"], [(2048, 2176)]),
    }
    for asset, pcm in expected.items():
        validate_fixture(staged[asset], pcm, asset_id=asset)
    assert _snapshot(tmp_path) == before
    assert not list(tmp_path.glob("native-prepare-*"))


def test_real_scratch_edit_changes_exactly_frames_1001_through_2006(
    tmp_path: Path,
) -> None:
    info = PCMFormat(32_000, 2, "s16", FRAMES, 3)
    source_pcm = _pcm(7)
    storage = WaveStorage()
    with audio_scratch(tmp_path, storage) as scratch:
        source = scratch.write_source(info, [source_pcm[:16_384], source_pcm[16_384:]])
        with storage.open(source) as reader:
            assert reader.info == info
        edited = scratch.edit(
            [
                (
                    frame_boundary_seconds(1001, info.rate, info.frames, "start"),
                    frame_boundary_seconds(2007, info.rate, info.frames, "end"),
                )
            ]
        )
        with storage.open(edited) as reader:
            assert reader.info == info
            result = b"".join(reader.blocks())
    assert result == (
        source_pcm[: 1001 * info.frame_bytes]
        + bytes((2007 - 1001) * info.frame_bytes)
        + source_pcm[2007 * info.frame_bytes :]
    )
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    ("mode", "detail"),
    [
        ("required frame", "required edit incomplete"),
        ("extra muted frame", "unaffected frames changed"),
        ("outside sample", "unaffected frames changed"),
        ("frame count", "frame count changed"),
    ],
)
def test_edit_completeness_or_fidelity_failure_is_atomic(
    tmp_path: Path, mode: str, detail: str
) -> None:
    assets, originals = _assets(tmp_path)
    decoder, encoder, _, encode_calls = _fake_codecs(assets, originals)
    storage = TamperingWaveStorage(mode, originals["a"], INFO)

    _assert_atomic_failure(
        tmp_path,
        assets,
        originals,
        _edits(),
        decoder,
        encoder,
        EditError,
        f"required asset a: PCM edit: {detail}",
        storage=storage,
    )
    assert encode_calls == []


@pytest.mark.parametrize("failing_asset_first", [False, True])
@pytest.mark.parametrize(
    ("corruption", "reason"),
    [
        ("truncated", "STRM file size mismatch"),
        ("unsupported", "unsupported AST codec"),
    ],
)
def test_late_native_validation_failure_is_atomic(
    tmp_path: Path, corruption: str, reason: str, failing_asset_first: bool
) -> None:
    assets, originals = _assets(tmp_path)
    if corruption == "truncated":
        assets["b"] = assets["b"][:-1]
    else:
        changed = bytearray(assets["b"])
        struct.pack_into(">H", changed, 8, 0)
        assets["b"] = bytes(changed)
    decoder, encoder, _, encode_calls = _fake_codecs(
        {asset: value for asset, value in assets.items() if asset != "b"}
        | {"b": build_canonical_ast(originals["b"])},
        originals,
    )
    edits = tuple(reversed(_edits())) if failing_asset_first else _edits()
    _assert_atomic_failure(
        tmp_path,
        assets,
        originals,
        edits,
        decoder,
        encoder,
        NativeValidationError,
        f"required asset b: native validation: {reason}",
    )
    assert encode_calls == ([] if failing_asset_first else ["a"])


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
        if asset_id == "b" and native_path.name == "source.ast":
            decode_calls.append(asset_id)
            raise OSError("injected extraction failure")
        normal_decoder(asset_id, native_path, pcm_path, info)

    _assert_atomic_failure(
        tmp_path,
        assets,
        originals,
        tuple(reversed(_edits())) if failing_asset_first else _edits(),
        fail_b,
        encoder,
        ExtractionError,
        "required asset b: extraction: injected extraction failure",
    )
    assert decode_calls == (["b"] if failing_asset_first else ["a", "a", "b"])
    assert encode_calls == ([] if failing_asset_first else ["a"])


def test_extraction_pcm_mismatch_inside_requested_mute_is_refused_before_encode(
    tmp_path: Path,
) -> None:
    assets, originals = _assets(tmp_path)
    decoder, encoder, _, encode_calls = _fake_codecs(assets, originals)

    def altered_decoder(
        asset_id: str, native_path: Path, pcm_path: Path, info: PCMFormat
    ) -> None:
        decoder(asset_id, native_path, pcm_path, info)
        if native_path.name == "source.ast" and asset_id == "a":
            changed = bytearray(pcm_path.read_bytes())
            changed[1001 * info.frame_bytes] ^= 1
            pcm_path.write_bytes(changed)

    with pytest.raises(ExtractionError) as error:
        prepare(
            tmp_path,
            assets,
            originals,
            _edits(),
            decoder=altered_decoder,
            encoder=encoder,
        )
    assert error.value.asset_id == "a"
    assert error.value.detail == "extracted PCM differs from verified source"
    assert encode_calls == []


def test_source_change_after_edit_is_refused_atomically(tmp_path: Path) -> None:
    assets, originals = _assets(tmp_path)
    decoder, encoder, _, encode_calls = _fake_codecs(assets, originals)
    _assert_atomic_failure(
        tmp_path,
        assets,
        originals,
        _edits(),
        decoder,
        encoder,
        EditError,
        "required asset a: PCM edit: native source changed during PCM edit",
        storage=SourceMutatingWaveStorage(),
    )
    assert encode_calls == []


def test_source_change_after_rebuild_is_refused_atomically(tmp_path: Path) -> None:
    assets, originals = _assets(tmp_path)
    decoder, normal_encoder, _, encode_calls = _fake_codecs(assets, originals)

    def tampering_encoder(
        asset_id: str, pcm_path: Path, native_path: Path, info: PCMFormat
    ) -> None:
        normal_encoder(asset_id, pcm_path, native_path, info)
        (native_path.parent / "source.ast").write_bytes(b"source changed after rebuild")

    _assert_atomic_failure(
        tmp_path,
        assets,
        originals,
        _edits(),
        decoder,
        tampering_encoder,
        ReconstructionError,
        "required asset a: reconstruction: native source changed during reconstruction",
    )
    assert encode_calls == ["a"]


def test_default_ast_validator_rejects_caller_supplied_nonprofile_sample_rate(
    tmp_path: Path,
) -> None:
    nonprofile = PCMFormat(44_100, 2, "s16", FRAMES, 3)
    decode_calls: list[str] = []
    encode_calls: list[str] = []
    with pytest.raises(
        ValueError, match="default AST validation requires the canonical PCM profile"
    ):
        prepare(
            tmp_path,
            {},
            {},
            (),
            decoder=lambda *_: decode_calls.append("decode"),
            encoder=lambda *_: encode_calls.append("encode"),
            info=nonprofile,
        )
    assert decode_calls == []
    assert encode_calls == []


def test_native_path_escape_is_refused_before_codec_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assets, originals = _assets(tmp_path)
    decode_calls: list[str] = []
    encode_calls: list[str] = []

    def escaping_path(directory: Path, filename: str) -> Path:
        if filename == "source.ast":
            return tmp_path / "outside.ast"
        return directory / filename

    monkeypatch.setattr(ast_core, "_native_path", escaping_path)
    with pytest.raises(
        ValueError, match="native path escaped private working directory"
    ):
        prepare(
            tmp_path,
            assets,
            originals,
            _edits(),
            decoder=lambda *_: decode_calls.append("decode"),
            encoder=lambda *_: encode_calls.append("encode"),
        )
    assert decode_calls == []
    assert encode_calls == []
    assert not (tmp_path / "outside.ast").exists()


@pytest.mark.parametrize("failing_asset_first", [False, True])
def test_edit_completeness_failure_is_atomic_in_both_asset_orders(
    tmp_path: Path, failing_asset_first: bool
) -> None:
    assets, originals = _assets(tmp_path)
    decoder, encoder, _, encode_calls = _fake_codecs(assets, originals)
    target_directory = "0" if failing_asset_first else "1"
    storage = TamperingWaveStorage(
        "required frame",
        originals["b"],
        INFO,
        target_directory=target_directory,
        tamper_frame=2048,
    )
    edits = tuple(reversed(_edits())) if failing_asset_first else _edits()
    _assert_atomic_failure(
        tmp_path,
        assets,
        originals,
        edits,
        decoder,
        encoder,
        EditError,
        "required asset b: PCM edit: required edit incomplete",
        storage=storage,
    )
    assert encode_calls == ([] if failing_asset_first else ["a"])


@pytest.mark.parametrize("failing_asset_first", [False, True])
def test_rebuilt_native_validation_failure_is_atomic_in_both_asset_orders(
    tmp_path: Path, failing_asset_first: bool
) -> None:
    assets, originals = _assets(tmp_path)
    encode_calls: list[str] = []
    decoder_pcm = {native: originals[asset] for asset, native in assets.items()}

    def happy_decoder(
        asset_id: str, native_path: Path, pcm_path: Path, info: PCMFormat
    ) -> None:
        del asset_id, info
        pcm_path.write_bytes(decoder_pcm[native_path.read_bytes()])

    def emit_noncanonical_ast(
        asset_id: str, pcm_path: Path, native_path: Path, info: PCMFormat
    ) -> None:
        encode_calls.append(asset_id)
        pcm = pcm_path.read_bytes()
        malformed = bytearray(build_canonical_ast(pcm, info))
        if asset_id == "b":
            malformed[72] = 1
        native = bytes(malformed)
        decoder_pcm[native] = pcm
        native_path.write_bytes(native)

    # The fake decoder deliberately returns the expected PCM for malformed bytes.
    edits = tuple(reversed(_edits())) if failing_asset_first else _edits()
    before = _snapshot(tmp_path)
    with pytest.raises(ReconstructionError) as error:
        prepare(
            tmp_path,
            assets,
            originals,
            edits,
            decoder=happy_decoder,
            encoder=emit_noncanonical_ast,
        )
    assert str(error.value) == (
        "required asset b: reconstruction: nonzero BLCK padding"
    )
    assert error.value.asset_id == "b"
    assert encode_calls == (["b"] if failing_asset_first else ["a", "b"])
    assert _snapshot(tmp_path) == before
    assert not list(tmp_path.glob("native-prepare-*"))


@pytest.mark.parametrize(
    "native_extension",
    [
        "",
        "/",
        "\\",
        "../escape.ast",
        "..\\..\\escape.ast",
        ".ast/../escape",
        ".ast\\..\\escape",
        "/absolute.ast",
        "\\\\server\\share\\escape.ast",
        "C:\\absolute.ast",
        "D:relative-drive.ast",
        "..",
        ".AST",
    ],
)
def test_native_extension_rejects_path_traversal_and_absolute_forms(
    tmp_path: Path, native_extension: str
) -> None:
    with pytest.raises(ValueError, match="native extension"):
        prepare(
            tmp_path,
            {},
            {},
            (),
            decoder=lambda *_: None,
            encoder=lambda *_: None,
            native_extension=native_extension,
        )


def test_late_shared_edit_failure_is_atomic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assets, originals = _assets(tmp_path)
    decoder, encoder, _, encode_calls = _fake_codecs(assets, originals)
    actual_edit = Scratch.edit

    def fail_second_asset(
        self: Scratch,
        ranges: Iterable[tuple[float, float]],
        *,
        before: float = 0,
        after: float = 0,
        fade: float = 0,
        curve: Curve = "cosine",
    ) -> Path:
        if self.directory.parent.parent.name == "1":
            raise OSError("injected PCM editor failure")
        return actual_edit(
            self,
            ranges,
            before=before,
            after=after,
            fade=fade,
            curve=curve,
        )

    monkeypatch.setattr(Scratch, "edit", fail_second_asset)
    _assert_atomic_failure(
        tmp_path,
        assets,
        originals,
        _edits(),
        decoder,
        encoder,
        EditError,
        "required asset b: PCM edit: injected PCM editor failure",
    )
    assert encode_calls == ["a"]


@pytest.mark.parametrize("failing_asset_first", [False, True])
def test_encoder_failure_with_valid_edited_pcm_is_atomic_in_both_orders(
    tmp_path: Path, failing_asset_first: bool
) -> None:
    assets, originals = _assets(tmp_path)
    decoder, normal_encoder, _, encode_calls = _fake_codecs(assets, originals)
    expected_b = _expected_edit(originals["b"], [(2048, 2176)])

    def fail_b(
        asset_id: str, pcm_path: Path, native_path: Path, info: PCMFormat
    ) -> None:
        if asset_id == "b":
            encode_calls.append(asset_id)
            assert pcm_path.is_file()
            assert pcm_path.read_bytes() == expected_b
            raise OSError("injected encoder failure")
        normal_encoder(asset_id, pcm_path, native_path, info)

    edits = tuple(reversed(_edits())) if failing_asset_first else _edits()
    message = "required asset b: reconstruction: injected encoder failure"
    _assert_atomic_failure(
        tmp_path,
        assets,
        originals,
        edits,
        decoder,
        fail_b,
        ReconstructionError,
        message,
    )
    assert "b" in encode_calls
    if failing_asset_first:
        assert encode_calls == ["b"]
    else:
        assert encode_calls == ["a", "b"]
