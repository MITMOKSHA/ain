"""Minimal .env loader (stdlib only).

Why this exists: API keys should not be exported by hand on every machine, and
they must never be committed. A gitignored `.env` file is the standard middle
ground - it survives shell restarts and travelling to another checkout, without
the key ever entering the repository.

Precedence: real environment variables always win over `.env`, so a one-off
`AIN_LLM_API_KEY=... python3 -m ain fetch` still overrides the file.
"""

from __future__ import annotations

import os
from pathlib import Path

_LOADED: set[str] = set()


def load_dotenv(root: Path, *, override: bool = False) -> list[str]:
    """Load KEY=VALUE pairs from <root>/.env into os.environ.

    Returns the names of variables that were set. Never raises: a malformed
    .env must not stop the agent from running.
    """
    path = Path(root) / ".env"
    if not path.exists():
        return []

    key = str(path.resolve())
    if key in _LOADED and not override:
        return []
    _LOADED.add(key)

    applied: list[str] = []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []

    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Tolerate a leading `export` so the file can also be sourced by shell.
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue

        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip()
        if not name:
            continue

        # Strip one layer of matching quotes.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]

        if override or name not in os.environ:
            os.environ[name] = value
            applied.append(name)

    return applied
