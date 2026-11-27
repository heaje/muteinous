"""Store-independent bounded provisional capability probing."""

from __future__ import annotations

import os
import stat
from collections import deque
from pathlib import Path

from . import context
from .models import Cancel, Candidate, ProbeResult

_MAX_PROBE_ENTRIES = 128
_MAX_PROBE_DEPTH = 2


def probe_installation(
    candidate: Candidate, *, cancelled: Cancel = context._never_cancel
) -> ProbeResult:
    """Inspect a shallow bounded sample of ordinary files, never decode or hash."""
    context._check(cancelled)
    if candidate.availability != "available":
        return ProbeResult(False, 0, ("installation unavailable",), True)
    issues: list[str] = []
    found = False
    examined = 0
    truncated = False
    pending: deque[tuple[Path, int]] = deque([(candidate.path, 0)])
    while pending and examined < _MAX_PROBE_ENTRIES:
        directory, depth = pending.popleft()
        context._check(cancelled)
        try:
            info = directory.lstat()
            if not context._ordinary(info) or not stat.S_ISDIR(info.st_mode):
                truncated = True
                issues.append(f"{directory}: not an ordinary directory")
                continue
            with os.scandir(directory) as entries:
                for entry in entries:
                    context._check(cancelled)
                    if examined >= _MAX_PROBE_ENTRIES:
                        truncated = True
                        break
                    examined += 1
                    try:
                        path = Path(entry.path)
                        info = path.lstat()
                        if not context._ordinary(info):
                            truncated = True
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            if depth < _MAX_PROBE_DEPTH:
                                pending.append((path, depth + 1))
                            else:
                                truncated = True
                        elif stat.S_ISREG(info.st_mode):
                            with path.open("rb", buffering=0) as stream:
                                found |= stream.read(4) == b"STRM"
                        else:
                            truncated = True
                    except OSError as error:
                        truncated = True
                        issues.append(f"{entry.path}: {error}")
        except OSError as error:
            truncated = True
            issues.append(f"{directory}: {error}")
    context._check(cancelled)
    return ProbeResult(found, examined, tuple(issues), truncated or bool(pending))
