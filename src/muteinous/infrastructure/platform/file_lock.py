"""Nonblocking exclusive lock on an already opened, nonempty owned lock file.

The caller owns the open handle for the entire protected lifetime; closing it
releases the lock. An OSError means ownership could not be established.
"""

import sys
from typing import BinaryIO

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


def lock_exclusive(stream: BinaryIO) -> None:
    stream.seek(0)
    if sys.platform == "win32":
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
