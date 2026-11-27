"""Epic Games Launcher manifest discovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import override

from .. import context
from .base import InstallationProvider


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("ambiguous JSON metadata key")
        result[key] = value
    return result


class EpicProvider(InstallationProvider):
    """Discover Epic installations from the configured manifest directory."""

    def __init__(self, directory: Path | None) -> None:
        self._directory = directory

    @override
    def discover(self, state: context.DiscoveryContext) -> None:
        directory = self._directory
        if directory is None:
            return
        for path in state.files(directory):
            if path.suffix.lower() != ".item":
                continue
            try:
                data = context._object(
                    json.loads(state.read(path), object_pairs_hook=_json_object)
                )
                if data.get("bIsIncompleteInstall") is True:
                    state.issue(path, "launcher reports incomplete installation")
                state.add(data.get("InstallLocation"), data.get("DisplayName"), "epic")
            except (OSError, ValueError, RecursionError) as error:
                state.issue(path, str(error))
