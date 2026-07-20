"""Locate an executable, falling back to a local .venv when it's not on PATH."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def find_executable(name: str, search_from: Path | None = None) -> str | None:
    found = shutil.which(name)
    if found:
        return found

    bin_dir = "Scripts" if sys.platform == "win32" else "bin"
    exe_name = f"{name}.exe" if sys.platform == "win32" else name

    start = (search_from or Path.cwd()).resolve()
    for d in (start, *start.parents):
        candidate = d / ".venv" / bin_dir / exe_name
        if candidate.exists():
            return str(candidate)
    return None
