"""Validated immutable bundles and guarded atomic current-result selection."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ._filesystem import (
    StorageError,
    canonical_json,
    checked_directory,
    checked_stat,
    digest,
    file_record,
    is_digest,
    is_token,
    read_json,
    read_regular,
    safe_name,
    walk_files,
)
from .space import SpaceRequirement, preflight, translate_write_error
from .staging import CleanupReport, Staging, StagingArea, try_lock

_METADATA = "integrity.json"
SELECTION_GUARD_TIMEOUT_SECONDS = 2.0
SELECTION_GUARD_POLL_INTERVAL_SECONDS = 0.01
DomainValidator = Callable[[Path], None]


@dataclass(frozen=True)
class ResultIdentity:
    """Opaque caller-validated source, effective configuration and generation."""

    source: str
    configuration: str
    generation: str

    def __post_init__(self) -> None:
        for value in (self.source, self.configuration, self.generation):
            if not isinstance(value, str) or not value:
                raise ValueError("Nonempty validity identities are required")
            value.encode("utf-8")


@dataclass(frozen=True)
class Selection:
    bundle: str
    metadata_sha256: str


@dataclass(frozen=True)
class UnreadableSelection:
    """Existing regular manifest whose bytes are not a valid selection."""

    raw_sha256: str


SelectionState = Selection | UnreadableSelection | None


def _result_key(result: str) -> str:
    if not isinstance(result, str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9_-]{0,63}", result
    ):
        raise ValueError("Invalid logical result key")
    # Windows reserved device names must also be rejected.
    safe_name(result)
    return result


def _metadata(
    directory: Path,
    result: str,
    bundle: str,
    identity: ResultIdentity,
    *,
    controlled_root: Path,
) -> bytes:
    records = []
    for path in walk_files(directory, controlled_root=controlled_root):
        relative = path.relative_to(directory).as_posix()
        if relative == _METADATA:
            continue
        if relative.casefold() == _METADATA:
            raise StorageError("Ambiguous reserved integrity metadata name")
        records.append(file_record(directory, path))
    if not records:
        raise StorageError("Result bundle has no payload files")
    return canonical_json(
        {
            "schema": 1,
            "result": result,
            "bundle": bundle,
            "source": identity.source,
            "configuration": identity.configuration,
            "generation": identity.generation,
            "files": records,
        }
    )


def _validate(
    directory: Path,
    result: str,
    selection: Selection,
    identity: ResultIdentity,
    validate_domain: DomainValidator,
    *,
    controlled_root: Path,
) -> None:
    raw = read_regular(directory / _METADATA, root=controlled_root)
    if digest(raw) != selection.metadata_sha256:
        raise StorageError("Integrity metadata digest mismatch")
    # Exact canonical equality with the freshly generated inventory rejects
    # unknown schemas, wrong types, duplicate keys, missing and extra members.
    if raw != _metadata(
        directory, result, selection.bundle, identity, controlled_root=controlled_root
    ):
        raise StorageError("Bundle identity, structure or integrity mismatch")
    validate_domain(directory)


def _prepare_publisher_file(staging: StagingArea, path: Path, name: str) -> None:
    if name in staging._publisher_files:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError(
                f"Cannot remove earlier publisher-created {name}"
            ) from exc
        staging._publisher_files.remove(name)
    elif os.path.lexists(path):
        raise StorageError(f"Reserved {name} is already present")


class ResultStore:
    """Storage under an explicitly application-owned, controlled directory.

    The caller must establish destination filesystem support for atomic
    directory rename, file replacement and exclusive OS leases before enabling
    publication or abandoned staging cleanup.
    No publication is attempted when that evidence is absent.
    """

    def __init__(self, root: Path, *, atomic_rename_supported: bool = False) -> None:
        self.root = root.absolute()
        self._atomic_rename_supported = atomic_rename_supported is True
        checked_directory(self.root, root=self.root)
        self._bundles = self.root / "bundles"
        self._current = self.root / "current"
        staging = self.root / "staging"
        leases = self.root / "stage-leases"
        for directory in (self._bundles, self._current, staging, leases):
            directory.mkdir(exist_ok=True)
            checked_directory(directory, root=self.root)
        self._staging = Staging(staging, leases, controlled_root=self.root)
        self._guard = self.root / "selection.lock"
        try:
            with self._guard.open("xb") as stream:
                stream.write(b"1")
        except FileExistsError:
            info = checked_stat(self._guard, directory=False)
            if info.st_size == 0:
                # An initializer may have crashed after exclusive creation but
                # before writing the lock byte. Appending is safe if concurrent
                # initializers both observe the empty file.
                with self._guard.open("ab") as stream:
                    stream.write(b"1")
                if checked_stat(self._guard, directory=False).st_size == 0:
                    raise StorageError("Selection guard could not be initialized")

    @contextmanager
    def stage(
        self,
        job_id: str,
        *,
        minimum_bytes: int = 0,
        estimate_bytes: int | None = None,
        other_requirements: tuple[SpaceRequirement, ...] = (),
    ) -> Iterator[StagingArea]:
        """Preflight known requirements; keep all staging users inside its lease."""
        staging_device = checked_directory(self._staging.root, root=self.root).st_dev
        if any(
            checked_directory(directory, root=self.root).st_dev != staging_device
            for directory in (self._bundles, self._current, self._staging.leases)
        ):
            raise StorageError("Staging requires destination-filesystem staging")
        requirements = (
            SpaceRequirement(self._staging.root, minimum_bytes, estimate_bytes),
            *other_requirements,
        )
        assessments = preflight(requirements, root=self.root)
        with self._staging.create(job_id, assessments) as area:
            yield area

    def cleanup_abandoned(self) -> CleanupReport:
        """Safely reclaim abandoned stages at startup or after jobs complete."""
        if not self._atomic_rename_supported:
            raise StorageError("Local filesystem lease semantics are not established")
        return self._staging.cleanup_abandoned()

    @contextmanager
    def _selection_guard(self) -> Iterator[None]:
        deadline = time.monotonic() + max(0.0, SELECTION_GUARD_TIMEOUT_SECONDS)
        while True:
            with try_lock(self._guard, root=self.root) as held:
                if held is not None:
                    yield
                    return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise StorageError("Result selection is busy; retry the operation")
            time.sleep(min(remaining, SELECTION_GUARD_POLL_INTERVAL_SECONDS))

    def _manifest_path(self, result: str) -> Path:
        checked_directory(self._current, root=self.root)
        return self._current / f"{_result_key(result)}.json"

    def _selection(self, result: str) -> SelectionState:
        path = self._manifest_path(result)
        try:
            raw = read_regular(path, root=self.root)
        except FileNotFoundError:
            # Missing manifest is the only absence condition, not a bad parent.
            checked_directory(self._current, root=self.root)
            return None
        try:
            value = read_json(raw)
            if (
                set(value) != {"schema", "bundle", "metadata_sha256"}
                or type(value["schema"]) is not int
                or value["schema"] != 1
                or not is_token(value["bundle"])
                or not is_digest(value["metadata_sha256"])
            ):
                raise StorageError("Invalid current result manifest")
        except StorageError:
            return UnreadableSelection(digest(raw))
        return Selection(value["bundle"], value["metadata_sha256"])

    def selection(self, result: str) -> SelectionState:
        """Capture the expected previous selection before producing a result."""
        with self._selection_guard():
            return self._selection(result)

    def publish(
        self,
        staging: StagingArea,
        result: str,
        identity: ResultIdentity,
        *,
        expected: SelectionState,
        is_current: Callable[[], bool],
        validate_domain: DomainValidator,
    ) -> Selection:
        """Commit one result; never replace an existing bundle directory.

        All writers/workers using the payload must have stopped and closed their
        files before this call. Publication validates a snapshot; concurrent
        payload mutation through the manifest switch violates the caller
        contract and is not defended against here. Every open_current call
        rehashes and refuses detected later modifications.

        The caller supplies a final authoritative generation/freshness check,
        synchronized with its source/configuration changes. The callback and
        expected-manifest comparisons run inside the selection guard. The guard
        waits briefly for contention and then refuses retryably. An ordinary
        refusal before rename leaves this stage retryable; after rename, any
        failure consumes it and may leave an unreferenced bundle. After an
        asynchronous BaseException, discard this stage and stage again because
        publisher metadata may have been left behind. Atomic manifest
        replacement is the commit point; after an ambiguous interruption,
        callers must reread selection(). Domain validators must be read-only and
        raise on invalid results.
        """
        _result_key(result)
        if staging._manager is not self._staging:
            raise StorageError("Staging belongs to a different result store")
        path = staging.path
        if not self._atomic_rename_supported:
            raise StorageError(
                "Atomic publication is not established for this filesystem"
            )
        integrity_path = path / _METADATA
        candidate_manifest = staging._directory / "candidate.json"
        destination: Path | None = None
        created_integrity = False
        created_candidate = False
        renamed = False
        rename_attempted = False
        try:
            device = checked_directory(path, root=self.root).st_dev
            if any(
                checked_directory(directory, root=self.root).st_dev != device
                for directory in (staging._directory, self._bundles, self._current)
            ):
                raise StorageError(
                    "Publication requires destination-filesystem staging"
                )
            _prepare_publisher_file(staging, integrity_path, _METADATA)
            _prepare_publisher_file(staging, candidate_manifest, "candidate.json")
            bundle = uuid4().hex
            metadata = _metadata(
                path, result, bundle, identity, controlled_root=self.root
            )
            selection = Selection(bundle, digest(metadata))
            manifest = canonical_json(
                {
                    "schema": 1,
                    "bundle": bundle,
                    "metadata_sha256": selection.metadata_sha256,
                }
            )
            preflight(
                [SpaceRequirement(staging._directory, len(metadata) + len(manifest))],
                root=self.root,
            )
            # Exclusive creation: staged inputs cannot provide their own metadata.
            with integrity_path.open("xb") as stream:
                created_integrity = True
                staging._publisher_files.add(_METADATA)
                stream.write(metadata)
            _validate(
                path,
                result,
                selection,
                identity,
                validate_domain,
                controlled_root=self.root,
            )
            with candidate_manifest.open("xb") as stream:
                created_candidate = True
                staging._publisher_files.add("candidate.json")
                stream.write(manifest)
            destination = self._bundles / bundle
            with self._selection_guard():
                if self._selection(result) != expected or is_current() is not True:
                    raise StorageError("Result producer was superseded")
                if os.path.lexists(destination):
                    raise StorageError("Bundle identity already exists")
                rename_attempted = True
                os.rename(path, destination)
                renamed = True
                staging._published = True
            # Hashing and domain validation run outside the short selection guard.
            _validate(
                destination,
                result,
                selection,
                identity,
                validate_domain,
                controlled_root=self.root,
            )
            with self._selection_guard():
                if self._selection(result) != expected or is_current() is not True:
                    raise StorageError("Result producer was superseded")
                os.replace(candidate_manifest, self._manifest_path(result))
                staging._committed = True
            return selection
        except OSError as exc:
            translate_write_error(exc)
        finally:
            if not renamed and rename_attempted and destination is not None:
                try:
                    destination.lstat()
                except FileNotFoundError:
                    pass
                except OSError:
                    # An indeterminate rename outcome must never expose a
                    # writable stage whose payload may already have moved.
                    renamed = True
                    staging._published = True
                else:
                    renamed = True
                    staging._published = True
            if not renamed:
                if created_candidate:
                    try:
                        candidate_manifest.unlink(missing_ok=True)
                    except OSError:
                        pass
                    else:
                        staging._publisher_files.discard("candidate.json")
                if created_integrity:
                    try:
                        integrity_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    else:
                        staging._publisher_files.discard(_METADATA)

    @contextmanager
    def open_current(
        self, result: str, identity: ResultIdentity, *, validate_domain: DomainValidator
    ) -> Iterator[Path]:
        """Yield a validated path for caller-convention read-only use.

        This does not hold a lifetime reader pin. Safety currently relies on this
        component never deleting published bundles; implement D112 reader
        acquisition before adding any published-bundle reclamation.
        """
        with self._selection_guard():
            selection = self._selection(result)
            if selection is None:
                raise StorageError("No committed result manifest")
            if isinstance(selection, UnreadableSelection):
                raise StorageError("Current result manifest is unreadable")
        checked_directory(self._bundles, root=self.root)
        path = self._bundles / selection.bundle
        try:
            _validate(
                path,
                result,
                selection,
                identity,
                validate_domain,
                controlled_root=self.root,
            )
        except OSError as exc:
            raise StorageError("Committed result cannot be verified") from exc
        with self._selection_guard():
            if self._selection(result) != selection:
                raise StorageError("Result selection changed during validation")
        # Bundles, including unreferenced and superseded versions, are retained.
        # No lifetime reference is acquired because this component never deletes.
        yield path
