"""Atomic file writing."""

import os
import tempfile
from pathlib import Path


def atomic_write(path: str | Path, content: str) -> None:
    """Write content to path atomically via temp file + rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    tmp_path = Path(tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        # BaseException so KeyboardInterrupt mid-write still cleans up.
        # missing_ok handles the case where os.replace already consumed it.
        tmp_path.unlink(missing_ok=True)
        raise
