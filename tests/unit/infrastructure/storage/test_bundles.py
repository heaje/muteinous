"""Storage unit tests for the corresponding infrastructure module."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast

import pytest

from muteinous.infrastructure.storage._filesystem import StorageError, canonical_json
from muteinous.infrastructure.storage.bundles import (
    ResultIdentity,
    _metadata,
    _result_key,
)

pytestmark = pytest.mark.portable


@pytest.mark.parametrize(
    ("value", "error"),
    [
        ("", ValueError),
        ("Uppercase", ValueError),
        ("x" * 65, ValueError),
        ("bad/name", ValueError),
        ("con", StorageError),
        (None, ValueError),
    ],
)
def test_result_key_rejects_invalid_keys(value: object, error: type[Exception]) -> None:
    with pytest.raises(error):
        _result_key(cast(str, value))


def test_result_key_preserves_valid_key() -> None:
    assert _result_key("result_1-v2") == "result_1-v2"


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
    assert (
        _metadata(tmp_path, "scan", bundle, identity, controlled_root=tmp_path)
        == expected
    )
    assert (
        _metadata(tmp_path, "scan", bundle, identity, controlled_root=tmp_path)
        == expected
    )
    assert canonical_json({"key": "é"}) == '{"key":"é"}'.encode("utf-8")
    assert canonical_json({"z": 2, "a": 1}) == b'{"a":1,"z":2}'


@pytest.mark.parametrize("field_index", [0, 1, 2])
@pytest.mark.parametrize(
    ("value", "error"),
    [("", ValueError), (None, ValueError), ("\ud800", UnicodeEncodeError)],
)
def test_result_identity_rejects_invalid_values_in_each_field(
    field_index: int, value: object, error: type[Exception]
) -> None:
    values: list[object] = ["source", "configuration", "generation"]
    values[field_index] = value
    with pytest.raises(error):
        ResultIdentity(*cast(tuple[str, str, str], tuple(values)))


def test_metadata_rejects_case_variant_integrity_metadata(tmp_path: Path) -> None:
    (tmp_path / "Integrity.JSON").write_bytes(b"producer metadata")
    with pytest.raises(StorageError, match="Ambiguous reserved"):
        _metadata(
            tmp_path,
            "scan",
            "0" * 32,
            ResultIdentity("source", "config", "generation"),
            controlled_root=tmp_path,
        )
