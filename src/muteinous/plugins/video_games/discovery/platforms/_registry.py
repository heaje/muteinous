"""Bounded read-only Windows registry access."""

from __future__ import annotations

from typing import SupportsInt

from .. import context

_MAX_REGISTRY_VALUE = 64 * 1024


def _registry_text(state: context.DiscoveryContext, key: SupportsInt, name: str) -> str:
    """Read a single REG_SZ with a fixed buffer, never an unbounded value query."""
    import ctypes
    import winreg
    from ctypes import wintypes

    context._check(state.cancelled)
    remaining = context._MAX_TOTAL_METADATA - state.bytes_read
    if remaining <= 0:
        raise context._LimitReached
    limit = min(remaining, _MAX_REGISTRY_VALUE)
    buffer = ctypes.create_string_buffer(limit)
    size = wintypes.DWORD(limit)
    kind = wintypes.DWORD()
    query = ctypes.WinDLL("advapi32.dll").RegQueryValueExW
    query.argtypes = [
        wintypes.HKEY,
        wintypes.LPCWSTR,
        wintypes.LPDWORD,
        wintypes.LPDWORD,
        wintypes.LPVOID,
        wintypes.LPDWORD,
    ]
    query.restype = wintypes.LONG
    status: int = query(
        wintypes.HKEY(int(key)),
        name,
        None,
        ctypes.byref(kind),
        buffer,
        ctypes.byref(size),
    )
    context._check(state.cancelled)
    if status and status != 2:
        # On failure, the amount transferred is unspecified. Charge the buffer.
        state.bytes_read += limit
    if status == 234:  # ERROR_MORE_DATA; do not allocate a larger buffer.
        state.truncated = True
        raise ValueError("registry metadata exceeds read limit")
    if status == 2:  # ERROR_FILE_NOT_FOUND
        raise FileNotFoundError(name)
    if status:
        raise ctypes.WinError(status)
    state.bytes_read += size.value
    if kind.value != winreg.REG_SZ:
        raise ValueError("unsupported registry metadata type")
    value = buffer.raw[: size.value].decode("utf-16-le").removesuffix("\x00")
    if not context._valid_text(value):
        raise ValueError("invalid registry metadata string")
    return value
