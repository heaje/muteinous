"""Validate the locked build environment against project requirements."""

import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest
from packaging.requirements import Requirement


@pytest.mark.portable
def test_locked_build_backends_satisfy_declared_requirements() -> None:
    root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))
    for spec in config["build-system"]["requires"]:
        requirement = Requirement(spec)
        assert requirement.specifier.contains(version(requirement.name)), spec
