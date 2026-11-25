"""Unit tests for staging ownership, leases and cleanup metadata."""

from __future__ import annotations

from pathlib import Path

import pytest

from muteinous.infrastructure.storage._filesystem import StorageError
from muteinous.infrastructure.storage.staging import (
    Staging,
    StagingArea,
)


@pytest.mark.portable
@pytest.mark.parametrize("raises_on_exit", [False, True])
def test_staging_area_is_unusable_after_owning_context_exits(
    tmp_path: Path, raises_on_exit: bool
) -> None:
    root = tmp_path / "storage"
    staging_root = root / "staging"
    leases = root / "stage-leases"
    staging_root.mkdir(parents=True)
    leases.mkdir()
    staging = Staging(staging_root, leases, controlled_root=root)
    areas: list[StagingArea] = []

    if raises_on_exit:
        with pytest.raises(RuntimeError, match="test interruption"):
            with staging.create("owner-exit", ()) as area:
                areas.append(area)
                assert area.path.is_dir()
                raise RuntimeError("test interruption")
    else:
        with staging.create("owner-exit", ()) as area:
            areas.append(area)
            assert area.path.is_dir()

    with pytest.raises(StorageError, match="no longer writable"):
        _ = areas[0].path
