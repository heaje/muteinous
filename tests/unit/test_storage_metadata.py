"""Deterministic result integrity and safe-path unit checks."""

import hashlib
from pathlib import Path

import pytest

from muteinous.infrastructure.storage._filesystem import (
    StorageError,
    canonical_json,
    read_json,
    safe_name,
)
from muteinous.infrastructure.storage.bundles import ResultIdentity, _metadata

pytestmark = pytest.mark.portable


def test_metadata_has_exact_canonical_bytes_and_order(tmp_path: Path) -> None:
    (tmp_path / "z.bin").write_bytes(b"z")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "member.txt").write_bytes(b"a")
    identity = ResultIdentity("source", "config", "generation")
    bundle = "0" * 32
    records = [
        {
            "path": "a/member.txt",
            "length": 1,
            "sha256": hashlib.sha256(b"a").hexdigest(),
        },
        {"path": "z.bin", "length": 1, "sha256": hashlib.sha256(b"z").hexdigest()},
    ]
    expected = canonical_json(
        {
            "bundle": bundle,
            "configuration": "config",
            "files": records,
            "generation": "generation",
            "result": "scan",
            "schema": 1,
            "source": "source",
        }
    )
    assert _metadata(tmp_path, "scan", bundle, identity) == expected
    assert _metadata(tmp_path, "scan", bundle, identity) == expected
    assert canonical_json({"key": "é"}) == '{"key":"é"}'.encode("utf-8")
    assert canonical_json({"z": 2, "a": 1}) == b'{"a":1,"z":2}'


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":1,"a":1}',
        b'{"a": 1}',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b'{"a":"\\ud800"}',
        b"[]",
        b"\xff",
        b"\xef\xbb\xbf{}",
    ],
)
def test_invalid_or_noncanonical_json_is_rejected(raw: bytes) -> None:
    with pytest.raises(StorageError):
        read_json(raw)


@pytest.mark.parametrize(
    "name",
    [
        "",
        ".",
        "..",
        "../escape",
        "a/b",
        "a\\b",
        "C:drive",
        "NUL.txt",
        "COM1",
        "x.",
        "x ",
        "a\x00",
    ],
)
def test_unsafe_path_components_are_rejected(name: str) -> None:
    with pytest.raises(StorageError):
        safe_name(name)
