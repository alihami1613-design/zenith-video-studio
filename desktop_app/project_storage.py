"""Durable atomic writes for user-authored ZENITH project files."""
from __future__ import annotations

import os
from pathlib import Path


def atomic_write_text(path: str | Path, content: str) -> Path:
    """Write UTF-8 text to a sibling temporary file, fsync, then atomically replace.

    The previous destination remains intact if writing or flushing fails.
    """
    target = Path(path)
    temporary = target.with_name(target.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return target
