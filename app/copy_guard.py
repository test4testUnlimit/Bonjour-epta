"""Know when the *user* pressed Ctrl+C — so we never eat their copy.

Bonjour grabs a selection by injecting Ctrl+C and then putting the previous
clipboard back. If the user's own Ctrl+C lands inside that window, the restore
overwrites what they just copied — "скопировал, вставил, а там прошлое".
That is the "работает через раз" report.

This hook marks real copy keystrokes so `selection.py` can step aside:
  * a fresh user copy → read the clipboard, do not inject, do not restore
  * a copy during our capture window → never restore

Detection is by scan code, not by key name: on a Cyrillic layout Ctrl+C is
Ctrl+Cyrillic_es and every name-based check misses it. Same lesson as the
v1.8.4 paste fix.

Our own injected Ctrl+C must not count as a user copy — hence `injecting()`.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager

from . import logutil

try:
    import keyboard
except ImportError:  # pragma: no cover - keyboard is a hard dep at runtime
    keyboard = None  # type: ignore

# scan codes, set 1 — layout independent
SC_C = 46
SC_X = 45
SC_INSERT = 82
_COPY_SCANS = frozenset((SC_C, SC_X, SC_INSERT))

# how long our own SendInput keeps the hook quiet after the call returns
INJECT_TAIL_S = 0.15

_lock = threading.Lock()
_last_copy_ts = 0.0
_inject_until = 0.0
_hook = None


def start() -> bool:
    """Install the hook. Idempotent; False if `keyboard` is unavailable."""
    global _hook
    if keyboard is None or _hook is not None:
        return _hook is not None
    try:
        _hook = keyboard.hook(_on_event, suppress=False)
    except Exception:  # noqa: BLE001
        logutil.exc("copy_guard hook")
        return False
    return True


def stop() -> None:
    global _hook
    if keyboard is None or _hook is None:
        return
    try:
        keyboard.unhook(_hook)
    except Exception:  # noqa: BLE001
        pass
    _hook = None


def _ctrl_down() -> bool:
    """`keyboard` tracks only real keys; GetAsyncKeyState is the fallback."""
    try:
        if keyboard.is_pressed("ctrl"):
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        import ctypes

        return bool(ctypes.windll.user32.GetAsyncKeyState(0x11) & 0x8000)
    except Exception:  # noqa: BLE001
        return False


def _on_event(event: object) -> None:
    """Runs on the keyboard listener thread — stay trivial."""
    if getattr(event, "event_type", None) != "down":
        return
    try:
        sc = int(getattr(event, "scan_code", 0))
    except Exception:  # noqa: BLE001
        return
    # `keyboard` reports `scan_code or -vk` (_winkeyboard.py:529). Our inject
    # now fills real scan codes + KEYEVENTF_SCANCODE; distinction from a finger
    # press is `injecting()` (time window), not missing scan. Ignore negative
    # vk-fallback codes from other synthesizers.
    if sc < 0:
        return
    if sc not in _COPY_SCANS:
        return
    now = time.perf_counter()
    with _lock:
        if now < _inject_until:
            return  # that was us
    if not _ctrl_down():
        return
    with _lock:
        global _last_copy_ts
        _last_copy_ts = now
    logutil.get().debug("user copy key sc=%s", sc)


@contextmanager
def injecting(tail_s: float = INJECT_TAIL_S):
    """Mark the window in which *we* synthesize Ctrl+C."""
    global _inject_until
    with _lock:
        _inject_until = max(_inject_until, time.perf_counter() + 1.0)
    try:
        yield
    finally:
        with _lock:
            _inject_until = time.perf_counter() + tail_s


def last_copy_ts() -> float:
    with _lock:
        return _last_copy_ts


def copied_since(t: float) -> bool:
    """Did the user press a copy key after `t` (a perf_counter stamp)?"""
    with _lock:
        return _last_copy_ts > t


def recent(within_s: float = 1.2) -> bool:
    """Did the user copy in the last `within_s` seconds?"""
    with _lock:
        ts = _last_copy_ts
    return bool(ts) and (time.perf_counter() - ts) <= within_s


def forget() -> None:
    """Tests / after we consumed the user's copy."""
    global _last_copy_ts
    with _lock:
        _last_copy_ts = 0.0
