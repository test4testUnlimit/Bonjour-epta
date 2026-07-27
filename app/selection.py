"""Selection capture — Crow Translate Windows approach (selection.cpp).

Crow (GPL-3, Hennadii Chernyshchyk):
  1) snapshot clipboard
  2) wait until Win/Shift/Alt/Ctrl are ALL unpressed
  3) SendInput Ctrl+C
  4) wait for clipboard change (up to ~1s)
  5) read text, restore clipboard

Extra (bonjur): unique marker on clipboard before Ctrl+C so re-selecting
the same string still registers a change. Without marker, if selection
== previous clipboard (common in Nova / Electron fields), we got empty.

Global lock: concurrent watcher threads must not interleave Ctrl+C/restore.

Marker hygiene: never return/leave __bonjur_* on clipboard or as selection
(large copies are slow; pyperclip may add \\r\\n — old endswith check missed those).
"""

from __future__ import annotations

import re
import sys
import threading
import time
import uuid

import pyperclip

from . import logutil

MARKER_PREFIX = "__bonjur_"
# uuid hex + delimiters; also accept any leftover junk after prefix
_MARKER_RE = re.compile(r"^\s*" + re.escape(MARKER_PREFIX) + r"[0-9a-fA-F]*__?\s*$")
_CLIP_LOCK = threading.Lock()

# Large selections: Ctrl+C can take >1s; keep polling while still on marker.
_HARD_CAP_S = 5.0
_STABLE_POLLS = 3
_STABLE_GAP_S = 0.04


def _mods_down_win() -> bool:
    """True if any of Win/Shift/Alt/Ctrl is currently down (GetAsyncKeyState)."""
    import ctypes

    user32 = ctypes.windll.user32
    keys = (
        0x5B,  # VK_LWIN
        0x5C,  # VK_RWIN
        0x10,  # VK_SHIFT
        0x11,  # VK_CONTROL
        0x12,  # VK_MENU (Alt)
    )
    for vk in keys:
        if user32.GetAsyncKeyState(vk) & 0x8000:
            return True
    return False


def _wait_mods_up(timeout_s: float = 2.0) -> bool:
    """Crow: while (GetAsyncKeyState(...)) {} — with timeout so we never hang."""
    if sys.platform != "win32":
        return True
    log = logutil.get()
    t0 = time.perf_counter()
    if not _mods_down_win():
        return True
    log.debug("waiting for modifiers release…")
    while time.perf_counter() - t0 < timeout_s:
        if not _mods_down_win():
            log.debug("modifiers up after %.0fms", (time.perf_counter() - t0) * 1000)
            time.sleep(0.03)
            return True
        time.sleep(0.01)
    log.warning("modifiers still down after %.1fs — proceed anyway", timeout_s)
    return False


def _send_ctrl_c_win() -> bool:
    """Crow: INPUT[4] Ctrl down, C down, C up, Ctrl up via SendInput."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    VK_CONTROL = 0x11
    VK_C = 0x43

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = (
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),
        )

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = (
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),
        )

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = (
            ("uMsg", wintypes.DWORD),
            ("wParamL", wintypes.WORD),
            ("wParamH", wintypes.WORD),
        )

    class INPUT_UNION(ctypes.Union):
        _fields_ = (("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT))

    class INPUT(ctypes.Structure):
        _fields_ = (("type", wintypes.DWORD), ("union", INPUT_UNION))

    def key(vk: int, flags: int = 0) -> INPUT:
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki = KEYBDINPUT(vk, 0, flags, 0, None)
        return inp

    try:
        arr = (INPUT * 4)(
            key(VK_CONTROL, 0),
            key(VK_C, 0),
            key(VK_C, KEYEVENTF_KEYUP),
            key(VK_CONTROL, KEYEVENTF_KEYUP),
        )
        n = user32.SendInput(4, ctypes.byref(arr), ctypes.sizeof(INPUT))
        return int(n) == 4
    except Exception:  # noqa: BLE001
        logutil.exc("SendInput Ctrl+C")
        return False


def _send_ctrl_c() -> bool:
    if sys.platform == "win32":
        if _send_ctrl_c_win():
            return True
    try:
        import keyboard

        keyboard.send("ctrl+c")
        return True
    except Exception:  # noqa: BLE001
        return False


def _clip_get() -> str:
    for _ in range(8):
        try:
            return pyperclip.paste() or ""
        except Exception:  # noqa: BLE001
            time.sleep(0.02)
    return ""


def _clip_set(text: str) -> bool:
    for _ in range(8):
        try:
            pyperclip.copy(text if text is not None else "")
            return True
        except Exception:  # noqa: BLE001
            time.sleep(0.02)
    return False


def _is_marker(text: str | None) -> bool:
    """True for our clipboard probe — strip whitespace/newlines; prefix is enough."""
    if not text:
        return False
    t = text.strip("\x00").strip()
    if not t:
        return False
    # any clipboard value that is (only) our marker, with optional trailing junk newlines
    if t.startswith(MARKER_PREFIX):
        # pure marker form, or marker + only whitespace already stripped
        if _MARKER_RE.match(t) or t.endswith("__"):
            return True
        # truncated / partial marker still not real user text
        if len(t) < 80 and all(c.isalnum() or c in "_-" for c in t):
            return True
    return False


def sanitize_selection(text: str | None) -> str:
    """Strip + drop marker — call at every boundary (hotkey, watcher, paste)."""
    if not text:
        return ""
    t = text.strip("\x00").strip()
    if not t or _is_marker(t):
        return ""
    # marker embedded as whole first line only (paranoia)
    first = t.splitlines()[0].strip() if t else ""
    if _is_marker(first) and len(t) < 100:
        return ""
    return t


def _ensure_not_marker_on_clipboard(previous: str) -> None:
    """If our probe is still on the clipboard, wipe it (never leave marker for user paste)."""
    try:
        got = _clip_get()
        if _is_marker(got):
            restore = previous if previous and not _is_marker(previous) else ""
            _clip_set(restore)
            logutil.get().warning("cleared leftover marker from clipboard")
    except Exception:  # noqa: BLE001
        pass


def get_selected_text(
    restore_clipboard: bool = True,
    settle_s: float = 1.0,
    *,
    clipboard_fallback: bool = False,
) -> str:
    """
    Crow-style selection grab + marker (same-text reselect safe). Never raises.
    settle_s: soft wait for clipboard change after Ctrl+C; extended while still marker.
    Never returns a marker string.
    """
    log = logutil.get()
    # serialize: dual mouse-up / hotkey+chip must not interleave Ctrl+C
    if not _CLIP_LOCK.acquire(timeout=3.0):
        log.warning("get_selected_text: clip lock busy")
        return ""
    try:
        return _get_selected_text_locked(
            restore_clipboard=restore_clipboard,
            settle_s=settle_s,
            clipboard_fallback=clipboard_fallback,
        )
    finally:
        _CLIP_LOCK.release()


def _get_selected_text_locked(
    *,
    restore_clipboard: bool,
    settle_s: float,
    clipboard_fallback: bool,
) -> str:
    log = logutil.get()
    log.debug(
        "get_selected_text CROW restore=%s settle=%.2f fallback=%s",
        restore_clipboard,
        settle_s,
        clipboard_fallback,
    )

    previous = ""
    try:
        previous = _clip_get()
    except Exception:  # noqa: BLE001
        logutil.exc("clip previous")
    if _is_marker(previous):
        previous = ""
    log.debug("clip previous len=%s head=%r", len(previous), previous[:80])

    marker = f"{MARKER_PREFIX}{uuid.uuid4().hex}__"
    try:
        if not _clip_set(marker):
            log.warning("marker set failed")
        else:
            # wait until marker is visible (clipboard APIs are racy)
            for _ in range(40):
                got_m = _clip_get()
                if got_m == marker or _is_marker(got_m):
                    break
                time.sleep(0.01)
            else:
                log.warning("marker not confirmed on clipboard")

        _wait_mods_up(2.0)

        if not _send_ctrl_c():
            log.warning("Ctrl+C send failed")
            if restore_clipboard:
                _clip_set(previous)
            _ensure_not_marker_on_clipboard(previous)
            if clipboard_fallback and previous and not _is_marker(previous):
                return sanitize_selection(previous)
            return ""

        # Wait until clipboard leaves the marker. Soft settle_s, hard cap for big text.
        soft = max(float(settle_s), 0.25)
        hard = max(soft, min(_HARD_CAP_S, soft * 4.0 if soft < 2 else _HARD_CAP_S))
        deadline_soft = time.perf_counter() + soft
        deadline_hard = time.perf_counter() + hard
        polls = 0
        selected = ""
        while time.perf_counter() < deadline_hard:
            time.sleep(0.03)
            polls += 1
            try:
                got = _clip_get()
            except Exception:  # noqa: BLE001
                continue
            if not got or _is_marker(got) or got == marker:
                # still marker: keep going until hard cap (large copy slow)
                continue

            # Real content — for large blobs wait until length stabilizes
            # (some apps fill clipboard in stages).
            candidate = got
            stable = 1
            last_len = len(candidate)
            for _ in range(_STABLE_POLLS - 1):
                time.sleep(_STABLE_GAP_S)
                try:
                    again = _clip_get()
                except Exception:  # noqa: BLE001
                    break
                if not again or _is_marker(again):
                    candidate = ""
                    break
                if len(again) == last_len and again == candidate:
                    stable += 1
                else:
                    candidate = again
                    last_len = len(again)
                    stable = 1
            if not candidate or _is_marker(candidate):
                continue
            if stable < 2 and last_len > 50_000:
                # huge text still growing — one more beat
                time.sleep(0.08)
                try:
                    again = _clip_get()
                    if again and not _is_marker(again):
                        candidate = again
                except Exception:  # noqa: BLE001
                    pass

            selected = sanitize_selection(candidate)
            if selected:
                log.debug(
                    "clip left marker after %s polls len=%s", polls, len(selected)
                )
                break

            # soft deadline exceeded and still nothing usable → give up soon
            if time.perf_counter() > deadline_soft and not selected:
                # only stop early if we've already left soft window AND
                # clipboard is non-marker empty-ish — else keep hard wait
                pass

        if restore_clipboard:
            _clip_set(previous)

        # Absolute hygiene: never leave probe on clipboard
        _ensure_not_marker_on_clipboard(previous)

        selected = sanitize_selection(selected)
        if selected:
            log.info("selected ok len=%s head=%r", len(selected), selected[:100])
            return selected

        if clipboard_fallback and previous and not _is_marker(previous):
            fb = sanitize_selection(previous)
            if fb:
                log.info("empty selection → fallback previous len=%s", len(fb))
                return fb

        log.warning("selection empty polls=%s", polls)
        return ""
    except Exception:  # noqa: BLE001
        logutil.exc("get_selected_text fatal")
        try:
            if restore_clipboard:
                _clip_set(previous)
        except Exception:  # noqa: BLE001
            pass
        _ensure_not_marker_on_clipboard(previous)
        if clipboard_fallback and previous and not _is_marker(previous):
            return sanitize_selection(previous)
        return ""
