"""Minimal installed-distribution smoke test (no application features yet)."""

from importlib import metadata
from pathlib import Path

import pytest

import muteinous


@pytest.mark.portable
def test_installed_distribution_imports() -> None:
    """Import resolves to a real package in an installed distribution."""
    assert metadata.version("muteinous")
    assert muteinous.__file__ is not None
    assert Path(muteinous.__file__).is_file()
