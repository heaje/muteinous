"""Apply discovery resource accounting to bounded registry reads."""

from __future__ import annotations

from typing import SupportsInt

from muteinous.infrastructure.platform import registry

from . import context

_MAX_REGISTRY_VALUE = 64 * 1024


def _registry_text(state: context.DiscoveryContext, key: SupportsInt, name: str) -> str:
    context._check(state.cancelled)
    remaining = context._MAX_TOTAL_METADATA - state.bytes_read
    if remaining <= 0:
        raise context._LimitReached
    result = registry.read_registry_text(key, name, min(remaining, _MAX_REGISTRY_VALUE))
    state.bytes_read += result.bytes_read
    state.truncated |= result.truncated
    context._check(state.cancelled)
    if result.error is not None:
        raise result.error
    return result.text
