import struct
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import pytest

from experiments.native_ast import ast_core
from experiments.native_ast.ast_core import (
    FRAMES,
    INFO,
    Decoder,
    Edit,
    EditError,
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
) -> tuple[Decoder, ast_core.Encoder, list[str], list[str]]:
    pcm_for_native = {native: originals[asset] for asset, native in assets.items()}
    decode_calls: list[str] = []
    encode_calls: list[str] = []

    def decoder(
        asset_id: str, native_path: Path, pcm_path: Path, info: PCMFormat
    ) -> None:
        decode_calls.append(asset_id)
        pcm_path.write_bytes(pcm_for_native[native_path.read_bytes()])

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


class _TamperingReader:
    def __init__(self, reader: Reader, mode: str, original: bytes) -> None:
        self._reader = reader
        self._mode = mode
        self._original = original
        self.info = reader.info

    def blocks(self) -> Iterator[bytes]:
        pcm = bytearray(b"".join(self._reader.blocks()))
        if self._mode == "required frame":
            offset = 1001 * self.info.frame_bytes
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


class _TamperingWaveStorage(WaveStorage):
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
    encoder: ast_core.Encoder,
    error_type: type[NativeStageError],
    message: str,
    *,
    expected_asset: str = "b",
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
    assert error.value.asset_id == expected_asset
    assert str(error.value) == message
    assert _snapshot(root) == before
    assert not list(root.glob("native-prepare-*"))
    return error.value


def test_prepare_merges_segment_edits_and_rebuilds_each_affected_asset_once(
    tmp_path: Path,
) -> None:
    assets, originals = _assets(tmp_path)
    assert ast_core.group_edits(assets, _edits()) == {
        "a": [(1001, 1257), (4000, 4050)],
        "b": [(2048, 2176)],
    }
    before = _snapshot(tmp_path)
    decoder, encoder, _, encode_calls = _fake_codecs(assets, originals)

    staged = prepare(
        tmp_path,
        assets,
        originals,
        _edits(),
        decoder=decoder,
        encoder=encoder,
    )

    assert set(staged) == {"a", "b"}
    assert Counter(encode_calls) == Counter({"a": 1, "b": 1})
    assert "untouched" not in encode_calls
    validate_fixture(
        staged["a"],
        _expected_edit(originals["a"], [(1001, 1257), (4000, 4050)]),
        asset_id="a",
    )
    validate_fixture(
        staged["b"],
        _expected_edit(originals["b"], [(2048, 2176)]),
        asset_id="b",
    )
    assert _snapshot(tmp_path) == before
    assert not list(tmp_path.glob("native-prepare-*"))


@pytest.mark.parametrize(
    ("field", "values"),
    [
        ("segment_start", (True, 4096, 100, 200)),
        ("segment_start", (10.0, 4096, 100, 200)),
        ("segment_frames", (0, True, 0, 1)),
        ("segment_frames", (0, 4096.0, 100, 200)),
        ("start", (0, 4096, True, 200)),
        ("start", (0, 4096, 100.0, 200)),
        ("end", (0, 4096, 0, True)),
        ("end", (0, 4096, 100, 200.0)),
    ],
)
def test_prepare_rejects_non_integer_edit_bounds_before_codec_calls(
    tmp_path: Path, field: str, values: tuple[object, object, object, object]
) -> None:
    assets, originals = _assets(tmp_path)
    decoder, encoder, decode_calls, encode_calls = _fake_codecs(assets, originals)
    invalid_bounds = cast(tuple[int, int, int, int], values)

    with pytest.raises(
        NativeValidationError, match=f"{field} must be an exact int"
    ) as error:
        prepare(
            tmp_path,
            assets,
            originals,
            (Edit("a", *invalid_bounds),),
            decoder=decoder,
            encoder=encoder,
        )

    assert error.value.asset_id == "a"
    assert decode_calls == []
    assert encode_calls == []


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
    assert result == _expected_edit(source_pcm, [(1001, 2007)])
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
def test_independent_edit_completeness_verifier_rejects_tampering_before_encode(
    tmp_path: Path, mode: str, detail: str
) -> None:
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
        f"required asset a: PCM edit: {detail}",
        expected_asset="a",
        storage=_TamperingWaveStorage(mode, originals["a"]),
    )
    assert encode_calls == []


@pytest.mark.parametrize(
    "failure",
    [
        "source native validation",
        "extraction mismatch",
        "shared editor failure",
        "encoder failure",
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
    if failure == "source native validation":
        malformed = bytearray(assets["b"])
        malformed[72] = 1
        assets["b"] = bytes(malformed)

    pcm_for_native = {native: originals[asset] for asset, native in assets.items()}
    decode_calls: list[str] = []
    encode_calls: list[str] = []

    def decoder(
        asset_id: str, native_path: Path, pcm_path: Path, info: PCMFormat
    ) -> None:
        decode_calls.append(asset_id)
        pcm = pcm_for_native[native_path.read_bytes()]
        if failure == "extraction mismatch" and asset_id == "b":
            pcm = bytes([pcm[0] ^ 1]) + pcm[1:]
        pcm_path.write_bytes(pcm)

    def encoder(
        asset_id: str, pcm_path: Path, native_path: Path, info: PCMFormat
    ) -> None:
        encode_calls.append(asset_id)
        if failure == "encoder failure" and asset_id == "b":
            raise OSError("injected encoder failure")
        native = bytearray(build_canonical_ast(pcm_path.read_bytes(), info))
        if failure == "rebuilt native validation" and asset_id == "b":
            native[72] = 1
        native_path.write_bytes(native)
        if failure != "rebuilt native validation" or asset_id != "b":
            pcm_for_native[bytes(native)] = pcm_path.read_bytes()

    error_types: dict[str, type[NativeStageError]] = {
        "source native validation": NativeValidationError,
        "extraction mismatch": ExtractionError,
        "shared editor failure": EditError,
        "encoder failure": ReconstructionError,
        "rebuilt native validation": ReconstructionError,
    }
    details = {
        "source native validation": "nonzero BLCK padding",
        "extraction mismatch": "extracted PCM differs from verified source",
        "shared editor failure": "injected PCM editor failure",
        "encoder failure": "injected encoder failure",
        "rebuilt native validation": "nonzero BLCK padding",
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
    error = _assert_atomic_failure(
        tmp_path,
        assets,
        originals,
        edits,
        decoder,
        encoder,
        error_types[failure],
        f"required asset b: {error_types[failure].stage}: {details[failure]}",
    )
    assert error.asset_id == "b"

    decoded_before_failure = {
        "source native validation": 0 if failing_asset_first else 2,
        "extraction mismatch": 1 if failing_asset_first else 3,
        "shared editor failure": 1 if failing_asset_first else 3,
        "encoder failure": 1 if failing_asset_first else 3,
        "rebuilt native validation": 1 if failing_asset_first else 3,
    }
    assert len(decode_calls) == decoded_before_failure[failure]
    if failure in (
        "source native validation",
        "extraction mismatch",
        "shared editor failure",
    ):
        assert encode_calls == ([] if failing_asset_first else ["a"])
    elif failure in ("encoder failure", "rebuilt native validation"):
        assert encode_calls == (["b"] if failing_asset_first else ["a", "b"])


def test_default_ast_preparation_rejects_nonprofile_pcm_metadata(
    tmp_path: Path,
) -> None:
    nonprofile = PCMFormat(44_100, 2, "s16", FRAMES, 3)
    codec_calls: list[str] = []
    with pytest.raises(
        ValueError, match="default AST validation requires the canonical PCM profile"
    ):
        prepare(
            tmp_path,
            {},
            {},
            (),
            decoder=lambda *_: codec_calls.append("decode"),
            encoder=lambda *_: codec_calls.append("encode"),
            info=nonprofile,
        )
    assert codec_calls == []


def test_native_extension_allowlist_and_path_containment_are_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="native extension"):
        prepare(
            tmp_path,
            {},
            {},
            (),
            decoder=lambda *_: None,
            encoder=lambda *_: None,
            native_extension="../escape.ast",
        )

    assets, originals = _assets(tmp_path)
    codec_calls: list[str] = []

    def escaping_path(directory: Path, filename: str) -> Path:
        if filename == "source.ast":
            return tmp_path / "outside.ast"
        return directory / filename

    monkeypatch.setattr(ast_core, "_native_path", escaping_path)
    before = _snapshot(tmp_path)
    with pytest.raises(
        ValueError, match="native path escaped private working directory"
    ):
        prepare(
            tmp_path,
            assets,
            originals,
            _edits(),
            decoder=lambda *_: codec_calls.append("decode"),
            encoder=lambda *_: codec_calls.append("encode"),
        )
    assert codec_calls == []
    assert _snapshot(tmp_path) == before
    assert not (tmp_path / "outside.ast").exists()
    assert not list(tmp_path.glob("native-prepare-*"))
