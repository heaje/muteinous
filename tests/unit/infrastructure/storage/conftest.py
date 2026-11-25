"""Fixtures for storage module unit tests."""

from pathlib import Path

import pytest

from muteinous.infrastructure.storage.bundles import ResultStore


@pytest.fixture
def store(tmp_path: Path) -> ResultStore:
    return ResultStore(tmp_path, atomic_rename_supported=True)
