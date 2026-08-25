"""OneInput protocol — "somebody else owns the keyboard right now".

Four programs on this machine independently claim the global keyboard: two AHK
dashboards (OneScript, MyDash), OpenWind's lock screen and this one. Bonjour is
the only one that *injects* Ctrl+C on an ordinary mouse drag, so it is the one
most likely to type into a lock screen that just came up.

The contract is two named Win32 mutexes; the full write-up lives in MemPalace
under general / input-arbiter.

    Local\\OneInput_Hotkeys_v1     which dashboard registers the shared chords
    Local\\OneInput_Exclusive_v1   input is busy — inject nothing at all

Bonjour only ever *reads* the exclusive one: it never takes over the keyboard
for a stretch of time, it just fires a single Ctrl+C. `hold()` exists for
symmetry and tests.

Windows releases a mutex when its owning process dies, so a crashed lock screen
can never leave us permanently muted — no timeouts or heartbeats needed.
"""

from __future__ import annotations

import sys
import threading
from contextlib import contextmanager

from . import logutil

MUTEX_EXCLUSIVE = "Local\\OneInput_Exclusive_v1"
MUTEX_HOTKEYS = "Local\\OneInput_Hotkeys_v1"

_SYNCHRONIZE = 0x00100000
_ERROR_ALREADY_EXISTS = 183

_lock = threading.Lock()
_held: dict[str, int] = {}


def _kernel32():
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        return ctypes.windll.kernel32
    except Exception:  # noqa: BLE001
        return None


def busy(name: str = MUTEX_EXCLUSIVE) -> bool:
    """True when another process holds `name`. Never raises.

    Fails *open* (returns False) if the check itself breaks — a broken probe
    must not silently disable selection capture forever.
    """
    k = _kernel32()
    if k is None:
        return False
    with _lock:
        if name in _held:
            return False  # we are the owner; not "somebody else"
    try:
        h = k.OpenMutexW(_SYNCHRONIZE, False, name)
    except Exception:  # noqa: BLE001
        logutil.exc("input_arbiter.busy")
        return False
    if not h:
        return False
    try:
        k.CloseHandle(h)
    except Exception:  # noqa: BLE001
        pass
    return True


def acquire(name: str = MUTEX_EXCLUSIVE) -> bool:
    """Take ownership. False if somebody already has it."""
    k = _kernel32()
    if k is None:
        return False
    with _lock:
        if name in _held:
            return True
        try:
            h = k.CreateMutexW(None, True, name)
        except Exception:  # noqa: BLE001
            logutil.exc("input_arbiter.acquire")
            return False
        if not h:
            return False
        if k.GetLastError() == _ERROR_ALREADY_EXISTS:
            try:
                k.CloseHandle(h)
            except Exception:  # noqa: BLE001
                pass
            return False
        _held[name] = h
        return True


def release(name: str = MUTEX_EXCLUSIVE) -> None:
    k = _kernel32()
    with _lock:
        h = _held.pop(name, None)
    if h and k is not None:
        try:
            k.CloseHandle(h)
        except Exception:  # noqa: BLE001
            pass


@contextmanager
def hold(name: str = MUTEX_EXCLUSIVE):
    """`with hold() as got:` — got is False when someone beat us to it."""
    got = acquire(name)
    try:
        yield got
    finally:
        if got:
            release(name)
