"""Result-storage integration tests for real filesystem boundaries."""

from __future__ import annotations

import errno
import json
import os
import shutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from muteinous.infrastructure.storage._filesystem import (
    StorageError,
    canonical_json,
    digest,
)
from muteinous.infrastructure.storage.bundles import (
    ResultIdentity,
    ResultStore,
    Selection,
    UnreadableSelection,
)
from tests.support.storage import IDENTITY, publish, read, validate_domain


@pytest.mark.portable
@pytest.mark.parametrize("damage", ["missing", "extra", "altered", "empty-directory"])
def test_reuse_rehashes_and_refuses_damaged_exact_bundle(
    store: ResultStore, damage: str
) -> None:
    publish(store, b"previous")
    selection = publish(store)
    assert read(store) == b"original"
    path = store.root / "bundles" / selection.bundle
    member = path / "payload.bin"
    if damage == "missing":
        member.unlink()
    elif damage == "extra":
        (path / "extra").write_bytes(b"unexpected")
    elif damage == "altered":
        before = member.stat()
        member.write_bytes(b"changed!")
        os.utime(member, ns=(before.st_atime_ns, before.st_mtime_ns))
    else:
        (path / "empty").mkdir()
    # No cached verdict, even when changed bytes retain length and mtime.
    with pytest.raises(StorageError):
        read(store)
    with pytest.raises(StorageError):
        read(ResultStore(store.root, atomic_rename_supported=True))


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema", True),
        ("schema", 2),
        ("source", "other"),
        ("files", [{"path": "../payload.bin", "length": 8, "sha256": "0" * 64}]),
        ("files", []),
    ],
)
def test_invalid_metadata_is_rejected_even_if_manifest_digest_matches(
    store: ResultStore, field: str, value: object
) -> None:
    selection = publish(store)
    path = store.root / "bundles" / selection.bundle / "integrity.json"
    metadata = json.loads(path.read_bytes())
    metadata[field] = value
    raw = canonical_json(metadata)
    path.write_bytes(raw)
    manifest = store.root / "current" / "scan.json"
    manifest.write_bytes(
        canonical_json(
            {"schema": 1, "bundle": selection.bundle, "metadata_sha256": digest(raw)}
        )
    )
    with pytest.raises(StorageError):
        read(store)


@pytest.mark.portable
@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "unsafe-bundle",
        "zero-digest",
        "noncanonical",
        "boolean-schema",
        "unknown-field",
        "invalid-digest-type",
        "null-digest",
        "list-digest",
        "invalid-digest-length",
        "uppercase-digest",
        "nonhex-digest",
        "short-bundle",
        "uppercase-bundle",
        "traversal-bundle",
        "nonstring-bundle",
    ],
)
@pytest.mark.parametrize("operation", ["selection", "open", "publish"])
def test_current_manifest_requires_exact_schema_for_all_operations(
    store: ResultStore, damage: str, operation: str
) -> None:
    selected = publish(store)
    manifest_path = store.root / "current" / "scan.json"
    if damage == "missing":
        manifest_path.unlink()
        manifest = None
    elif damage == "noncanonical":
        manifest_path.write_bytes(manifest_path.read_bytes() + b"\n")
        manifest = None
    else:
        manifest = json.loads(manifest_path.read_bytes())
        if damage == "unsafe-bundle":
            manifest["bundle"] = "../staging"
            manifest["metadata_sha256"] = "0" * 64
        elif damage == "zero-digest":
            manifest["metadata_sha256"] = "0" * 64
        elif damage == "boolean-schema":
            manifest["schema"] = True
        elif damage == "unknown-field":
            manifest["unexpected"] = "not allowed"
        elif damage == "invalid-digest-type":
            manifest["metadata_sha256"] = 123
        elif damage == "null-digest":
            manifest["metadata_sha256"] = None
        elif damage == "list-digest":
            manifest["metadata_sha256"] = []
        elif damage == "invalid-digest-length":
            manifest["metadata_sha256"] = "0" * 63
        elif damage == "uppercase-digest":
            manifest["metadata_sha256"] = "A" * 64
        elif damage == "nonhex-digest":
            manifest["metadata_sha256"] = "g" * 64
        elif damage == "short-bundle":
            manifest["bundle"] = "short"
        elif damage == "uppercase-bundle":
            manifest["bundle"] = "A" * 32
        elif damage == "traversal-bundle":
            manifest["bundle"] = "../x"
        else:
            manifest["bundle"] = 123
        manifest_path.write_bytes(canonical_json(manifest))

    if operation == "selection":
        current = store.selection("scan")
        if damage == "missing":
            assert current is None
        elif damage == "zero-digest":
            assert isinstance(current, Selection)
            assert current.metadata_sha256 == "0" * 64
        else:
            assert isinstance(current, UnreadableSelection)
    elif operation == "open":
        with pytest.raises(StorageError):
            with store.open_current("scan", IDENTITY, validate_domain=validate_domain):
                pytest.fail("Invalid or missing current manifest was exposed")
    else:
        with store.stage("invalid-current-manifest") as stage:
            (stage.path / "payload.bin").write_bytes(b"must-not-publish")
            with pytest.raises(StorageError):
                store.publish(
                    stage,
                    "scan",
                    IDENTITY,
                    expected=selected,
                    is_current=lambda: True,
                    validate_domain=validate_domain,
                )


@pytest.mark.portable
def test_missing_selected_bundle_refuses_open_without_fallback(
    store: ResultStore,
) -> None:
    older = publish(store, b"older")
    selected = publish(store, b"selected")
    shutil.rmtree(store.root / "bundles" / selected.bundle)

    with pytest.raises(StorageError, match="Committed result cannot be verified"):
        read(store)
    assert store.selection("scan") == selected
    assert (
        store.root / "bundles" / older.bundle / "payload.bin"
    ).read_bytes() == b"older"


@pytest.mark.portable
@pytest.mark.parametrize(
    ("result", "error"),
    [
        ("Uppercase", ValueError),
        ("x" * 65, ValueError),
        ("bad/name", ValueError),
        ("con", StorageError),
        ("", ValueError),
    ],
)
@pytest.mark.parametrize("operation", ["selection", "publish", "open"])
def test_invalid_logical_result_keys_are_refused_by_public_operations(
    store: ResultStore,
    result: str,
    error: type[Exception],
    operation: str,
) -> None:
    if operation == "selection":
        with pytest.raises(error):
            store.selection(result)
    elif operation == "open":
        with pytest.raises(error):
            with store.open_current(result, IDENTITY, validate_domain=validate_domain):
                pytest.fail("Invalid logical result key was exposed")
    else:
        with store.stage("invalid-result-key") as stage:
            (stage.path / "payload.bin").write_bytes(b"must-not-publish")
            with pytest.raises(error):
                store.publish(
                    stage,
                    result,
                    IDENTITY,
                    expected=None,
                    is_current=lambda: True,
                    validate_domain=validate_domain,
                )


@pytest.mark.parametrize(
    "identity",
    [
        ResultIdentity("different-source", "config-a", "generation-a"),
        ResultIdentity("source-a", "different-config", "generation-a"),
        ResultIdentity("source-a", "config-a", "different-generation"),
    ],
)
def test_source_configuration_and_generation_are_required_on_every_reuse(
    store: ResultStore, identity: ResultIdentity
) -> None:
    publish(store)
    assert read(store) == b"original"
    with pytest.raises(StorageError):
        read(store, identity)


def test_domain_failure_prevents_publication_and_reuse(store: ResultStore) -> None:
    first = publish(store)

    def reject(path: Path) -> None:
        raise StorageError("Domain validation refused")

    with store.stage("invalid") as stage:
        (stage.path / "payload.bin").write_bytes(b"invalid")
        with pytest.raises(StorageError, match="Domain validation"):
            store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=first,
                is_current=lambda: True,
                validate_domain=reject,
            )
    assert store.selection("scan") == first
    with pytest.raises(StorageError, match="Domain validation"):
        with store.open_current("scan", IDENTITY, validate_domain=reject):
            pytest.fail("Invalid domain result was exposed")


@pytest.mark.portable
def test_slow_open_validation_does_not_hold_selection_guard(store: ResultStore) -> None:
    selection = publish(store)
    validating = threading.Event()
    continue_validation = threading.Event()

    def slow_validator(path: Path) -> None:
        validate_domain(path)
        validating.set()
        if not continue_validation.wait(5):
            raise TimeoutError("Test did not release slow validation")

    def slow_open() -> bytes:
        with store.open_current(
            "scan", IDENTITY, validate_domain=slow_validator
        ) as path:
            return (path / "payload.bin").read_bytes()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(slow_open)
        assert validating.wait(5), "Open validation did not start"
        try:
            assert store.selection("scan") == selection
            with store.open_current(
                "scan", IDENTITY, validate_domain=validate_domain
            ) as path:
                assert (path / "payload.bin").read_bytes() == b"original"
        finally:
            continue_validation.set()
        assert future.result(timeout=5) == b"original"


@pytest.mark.portable
def test_publish_racing_with_open_recheck_refuses_stale_open(
    store: ResultStore,
) -> None:
    old = publish(store)
    validating = threading.Event()
    continue_validation = threading.Event()

    def slow_validator(path: Path) -> None:
        validate_domain(path)
        validating.set()
        if not continue_validation.wait(5):
            raise TimeoutError("Test did not release slow validation")

    def slow_open() -> None:
        with store.open_current("scan", IDENTITY, validate_domain=slow_validator):
            pass

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(slow_open)
        assert validating.wait(5), "Open validation did not start"
        try:
            new = publish(store, b"new-current")
        finally:
            continue_validation.set()
        with pytest.raises(StorageError, match="selection changed"):
            future.result(timeout=5)
    assert new != old
    assert store.selection("scan") == new
    assert read(store) == b"new-current"


@pytest.mark.portable
def test_hardlinked_payload_is_refused(store: ResultStore, tmp_path: Path) -> None:
    target = tmp_path / "unrelated.bin"
    target.write_bytes(b"untouched")
    with store.stage("hardlink") as stage:
        os.link(target, stage.path / "payload.bin")
        with pytest.raises(StorageError, match="Unexpected filesystem entry"):
            store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=None,
                is_current=lambda: True,
                validate_domain=validate_domain,
            )
    assert target.read_bytes() == b"untouched"
    assert store.selection("scan") is None


@pytest.mark.portable
def test_alternate_data_streams_are_refused_during_publish_and_open(
    store: ResultStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = publish(store, b"previous")
    stream_target: list[Path | None] = [None]

    if sys.platform != "win32":

        def injected_streams(path: Path) -> tuple[str, ...]:
            if path == stream_target[0]:
                return ("::$DATA", ":review:$DATA")
            return ("::$DATA",)

        monkeypatch.setattr(
            "muteinous.infrastructure.storage._filesystem._enumerate_streams",
            injected_streams,
            raising=False,
        )

    def add_review_stream(path: Path) -> None:
        if sys.platform == "win32":
            stream = Path(f"{path}:review")
            stream.write_bytes(b"unhashed review stream")
            assert stream.read_bytes() == b"unhashed review stream"
        else:
            stream_target[0] = path

    with store.stage("alternate-stream-file") as stage:
        payload = stage.path / "payload.bin"
        payload.write_bytes(b"candidate")
        add_review_stream(payload)
        with pytest.raises(StorageError, match="alternate data stream"):
            store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=previous,
                is_current=lambda: True,
                validate_domain=validate_domain,
            )
    assert store.selection("scan") == previous
    assert read(store) == b"previous"

    with store.stage("alternate-stream-directory") as stage:
        payload = stage.path / "payload.bin"
        payload.write_bytes(b"candidate")
        nested = stage.path / "nested"
        nested.mkdir()
        (nested / "member.bin").write_bytes(b"nested payload")
        add_review_stream(nested)
        with pytest.raises(StorageError, match="alternate data stream"):
            store.publish(
                stage,
                "scan",
                IDENTITY,
                expected=previous,
                is_current=lambda: True,
                validate_domain=validate_domain,
            )
    assert store.selection("scan") == previous
    assert read(store) == b"previous"

    published_payload = store.root / "bundles" / previous.bundle / "payload.bin"
    add_review_stream(published_payload)
    with pytest.raises(StorageError, match="alternate data stream"):
        read(store)
    assert store.selection("scan") == previous


@pytest.mark.portable
@pytest.mark.parametrize("error_number", [errno.EACCES, errno.EIO])
@pytest.mark.parametrize("operation", ["selection", "publish", "open"])
def test_manifest_read_io_errors_are_not_treated_as_absence(
    store: ResultStore,
    monkeypatch: pytest.MonkeyPatch,
    error_number: int,
    operation: str,
) -> None:
    previous = publish(store, b"previous")
    manifest = store.root / "current" / "scan.json"
    original_read_bytes = Path.read_bytes
    read_error = OSError(error_number, "injected manifest read failure")

    def fail_manifest_read(path: Path) -> bytes:
        if path == manifest:
            raise read_error
        return original_read_bytes(path)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", fail_manifest_read)
        if operation == "selection":
            with pytest.raises(OSError) as raised:
                store.selection("scan")
        elif operation == "open":
            with pytest.raises(OSError) as raised:
                with store.open_current(
                    "scan", IDENTITY, validate_domain=validate_domain
                ):
                    pytest.fail("Manifest read error was treated as no selection")
        else:
            with store.stage("manifest-read-error") as stage:
                (stage.path / "payload.bin").write_bytes(b"must-not-publish")
                with pytest.raises(OSError) as raised:
                    store.publish(
                        stage,
                        "scan",
                        IDENTITY,
                        expected=previous,
                        is_current=lambda: True,
                        validate_domain=validate_domain,
                    )
    assert raised.value is read_error
    assert store.selection("scan") == previous
    assert read(store) == b"previous"
