"""Sidebar options, kept in the cache dir: a reload or a restart starts from the last ones."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

CACHE_FILE = (
    Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    / "panoloc"
    / "sidebar.json"
)


def load(defaults: dict[str, Any]) -> dict[str, Any]:
    """The defaults, overridden by the saved options that still fit them (same key, same type)."""
    try:
        saved = json.loads(CACHE_FILE.read_text())
    except OSError, ValueError:  # not saved yet, or a broken file
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    return {
        k: saved[k] if type(saved.get(k)) is type(v) else v
        for k, v in defaults.items()
    }


def save(options: dict[str, Any]) -> None:
    """Best effort: a read-only cache dir only means the options are not remembered."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", dir=CACHE_FILE.parent, suffix=".part", delete=False
        ) as fh:
            json.dump(options, fh, indent=2)
        # atomic: two tabs saving at once never leave a half-written file
        Path(fh.name).replace(CACHE_FILE)
    except OSError:
        pass
