from pathlib import Path

import pytest

from muteinous.infrastructure.platform.file_lock import lock_exclusive

pytestmark = pytest.mark.portable


def test_second_handle_cannot_lock_same_file_while_first_holds_lock(
    tmp_path: Path,
) -> None:
    path = tmp_path / "owned.lock"
    path.write_bytes(b"lock")

    with path.open("r+b") as first, path.open("r+b") as second:
        lock_exclusive(first)
        with pytest.raises(OSError):
            lock_exclusive(second)


def test_closing_first_handle_releases_lock_for_second_handle(tmp_path: Path) -> None:
    path = tmp_path / "owned.lock"
    path.write_bytes(b"lock")
    first = path.open("r+b")
    second = path.open("r+b")

    try:
        lock_exclusive(first)
        with pytest.raises(OSError):
            lock_exclusive(second)
        first.close()
        lock_exclusive(second)
    finally:
        first.close()
        second.close()


def test_lock_can_be_taken_on_already_open_nonempty_file(tmp_path: Path) -> None:
    path = tmp_path / "owned.lock"
    path.write_bytes(b"already has content")

    with path.open("r+b") as stream:
        stream.seek(5)
        lock_exclusive(stream)


def test_lock_on_one_file_does_not_block_a_different_file(tmp_path: Path) -> None:
    first_path = tmp_path / "first.lock"
    second_path = tmp_path / "second.lock"
    first_path.write_bytes(b"first")
    second_path.write_bytes(b"second")

    with first_path.open("r+b") as first, second_path.open("r+b") as second:
        lock_exclusive(first)
        lock_exclusive(second)
