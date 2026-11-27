"""Read-only launcher discovery and provisional installation probing."""

from .models import (
    Availability,
    Cancel,
    Candidate,
    DiscoveryCancelled,
    DiscoveryResult,
    ProbeResult,
    Source,
)
from .probe import probe_installation
from .service import discover_installations, discover_windows, select_folder

__all__ = [
    "Availability",
    "Cancel",
    "Candidate",
    "DiscoveryCancelled",
    "DiscoveryResult",
    "ProbeResult",
    "Source",
    "discover_installations",
    "discover_windows",
    "probe_installation",
    "select_folder",
]
