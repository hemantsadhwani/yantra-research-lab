"""Minimal .env loader — standard library only, zero dependencies.

Reads ``KEY=VALUE`` lines from a local ``.env`` file into ``os.environ`` so scripts can pick up
secrets (e.g. ``ANTHROPIC_API_KEY``) without hardcoding them. Existing environment variables are
NOT overwritten (env wins over the file), which is the usual precedence for local dev vs deploy.

Usage:
    from load_env import load_env
    load_env()                       # loads ./.env if present
    import os; os.environ["ANTHROPIC_API_KEY"]

The ``.env`` file is git-ignored — never commit real secrets. See ``.env.example`` for the keys.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env(path: str | os.PathLike = ".env") -> bool:
    """Load KEY=VALUE pairs from ``path`` into ``os.environ`` (without overwriting existing vars).

    Returns True if the file was found and read, False if it was absent (a no-op, not an error).
    """
    p = Path(path)
    if not p.exists():
        return False
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, val)
    return True


if __name__ == "__main__":  # quick self-check: does it find a key? (never prints the secret)
    found = load_env()
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    print(f".env loaded: {found} · ANTHROPIC_API_KEY present: {has_key}")
