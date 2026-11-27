"""Immutable candidate and provisional discovery results."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Source = Literal["steam", "epic", "gog", "manual"]
Availability = Literal["available", "missing", "inaccessible"]
Cancel = Callable[[], bool]


class DiscoveryCancelled(Exception):
    """The caller cancelled; no partial result should be published."""


@dataclass(frozen=True)
class Candidate:
    path: Path
    name: str
    sources: tuple[Source, ...]
    availability: Availability


@dataclass(frozen=True)
class DiscoveryResult:
    candidates: tuple[Candidate, ...]
    issues: tuple[str, ...]
    truncated: bool


@dataclass(frozen=True)
class ProbeResult:
    # A signature is evidence for further investigation, not a supported reader.
    ast_signature: bool
    entries_examined: int
    issues: tuple[str, ...]
    truncated: bool
