"""Where the AI gateway lives — read from ~/.bonjur-epta/ai.json, never from git.

The host, tenant and client id are site-specific, so they stay on the machine
like a local acronym pack does. `ai.example.json` in the repo shows the shape.
No file → `configured()` is False and every AI button stays grey.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from . import logutil

CONFIG_PATH = Path.home() / ".bonjur-epta" / "ai.json"

# Plain vendor slugs — nothing site-specific, so they can live in git. A gateway
# that serves something else lists its own under "models" in ai.json.
DEFAULT_MODELS = (
    "claude-opus-4-6",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
    "gemini-3.1-pro",
    "gemini-3-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
)

_lock = threading.Lock()
_cache: dict | None = None
_loaded = False


def _load() -> dict:
    global _cache, _loaded
    with _lock:
        if _loaded:
            return _cache or {}
        _loaded = True
        try:
            if CONFIG_PATH.is_file():
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    _cache = data
        except Exception:  # noqa: BLE001
            logutil.exc("ai_config: cannot read %s" % CONFIG_PATH)
            _cache = None
        return _cache or {}


def reload() -> None:
    """Pick up an ai.json dropped in while the app was running."""
    global _cache, _loaded
    with _lock:
        _cache = None
        _loaded = False


def configured() -> bool:
    d = _load()
    return bool(d.get("host") and d.get("path"))


def host() -> str:
    return str(_load().get("host") or "")


def path() -> str:
    return str(_load().get("path") or "")


def origin() -> str:
    return str(_load().get("origin") or "")


def agent_slug() -> str:
    return str(_load().get("agent_slug") or "")


def model() -> str:
    """Model slug from the config; settings can override it."""
    return str(_load().get("model") or "")


def models() -> list[str]:
    """What the model picker offers — config list first, the built-in one otherwise."""
    raw = _load().get("models")
    got = [str(m).strip() for m in raw if str(m).strip()] if isinstance(raw, list) else []
    out = got or list(DEFAULT_MODELS)
    fixed = model()
    if fixed and fixed not in out:
        out.insert(0, fixed)
    return out


def oauth() -> dict:
    d = _load().get("oauth")
    return d if isinstance(d, dict) else {}


def can_refresh() -> bool:
    o = oauth()
    return bool(o.get("host") and o.get("tenant") and o.get("client_id"))


def where() -> str:
    """Human-readable location for the settings window."""
    return str(CONFIG_PATH)
