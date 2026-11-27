"""Epic Games Launcher manifest discovery."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import override

from muteinous.infrastructure.platform.environment import OperatingSystem

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

    def __init__(
        self, directory: Callable[[context.DiscoveryContext], Path | None] | None = None
    ) -> None:
        self._directory = directory

    @override
    def discover(self, state: context.DiscoveryContext) -> None:
        source = self._directory
        if source is None:
            if state.os != OperatingSystem.WINDOWS:
                state.issue("Epic", f"automatic discovery unavailable on {state.os}")
                return
            source = self._windows_directory
        directory = source(state)
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

    @staticmethod
    def _windows_directory(state: context.DiscoveryContext) -> Path | None:
        program_data = os.environ.get("ProgramData")
        epic = (
            Path(program_data) / "Epic/EpicGamesLauncher/Data/Manifests"
            if program_data
            else None
        )
        if epic is None or not context._valid_path(epic):
            state.issue("Epic", "missing or invalid ProgramData location")
            epic = None
        return epic
