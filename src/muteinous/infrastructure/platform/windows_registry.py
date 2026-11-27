"""Bounded, read-only Windows registry text access."""

from __future__ import annotations

import ctypes
import winreg
from ctypes import wintypes
from dataclasses import dataclass
from typing import SupportsInt


@dataclass(frozen=True)
class RegistryReadResult:
    """Report bytes charged even on failed reads; error is absent on success."""

    bytes_read: int
    text: str = ""
    error: OSError | ValueError | None = None
    truncated: bool = False


def read_registry_text(
    key: SupportsInt, name: str, max_bytes: int
) -> RegistryReadResult:
    """Read one REG_SZ, without reallocating on an oversized value."""
    if not 0 < max_bytes <= 0xFFFFFFFF:
        raise ValueError("registry read limit must fit a positive DWORD")
    limit = max_bytes
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
    if status == 234:  # ERROR_MORE_DATA; amount transferred is unspecified.
        return RegistryReadResult(
            limit,
            error=ValueError("registry metadata exceeds read limit"),
            truncated=True,
        )
    if status == 2:  # ERROR_FILE_NOT_FOUND
        return RegistryReadResult(0, error=FileNotFoundError(name))
    if status:
        return RegistryReadResult(limit, error=ctypes.WinError(status))
    if kind.value != winreg.REG_SZ:
        return RegistryReadResult(
            size.value, error=ValueError("unsupported registry metadata type")
        )
    try:
        value = buffer.raw[: size.value].decode("utf-16-le").removesuffix("\x00")
    except UnicodeError as error:
        return RegistryReadResult(size.value, error=error)
    if "\x00" in value:
        return RegistryReadResult(
            size.value, error=ValueError("invalid registry metadata string")
        )
    return RegistryReadResult(size.value, text=value)
