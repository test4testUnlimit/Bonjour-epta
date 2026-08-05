"""Selection capture — Crow Translate Windows approach (selection.cpp).

Crow (GPL-3, Hennadii Chernyshchyk):
  1) snapshot clipboard
  2) wait until Win/Shift/Alt/Ctrl are ALL unpressed
  3) SendInput Ctrl+C
  4) wait for clipboard change (up to ~1s)
  5) read text, restore clipboard

Change detection: GetClipboardSequenceNumber() — Windows bumps it on EVERY
clipboard write, even re-copying identical text. That is the exact case the
old __bonjur_* marker was invented for, so the marker is gone entirely.

Why no marker anymore (critical bug fix):
  We must NEVER write to the global clipboard before Ctrl+C. The old code put
  a probe string on the clipboard; on a large/slow copy the restore raced and
  the probe survived — the user's next paste was `__bonjur_<uuid>__`. Using the
  sequence number means bonjur reads/restores the clipboard but never writes a
  probe, so a probe can never leak into the user's paste. Class of bug removed.

Global lock: concurrent watcher threads must not interleave Ctrl+C/restore.

sanitize_selection / _is_marker stay as defence-in-depth: strip any stray
__bonjur_* left on the clipboard by an older build still running elsewhere.

Ctrl+C "works every other time" — three rules were missing:

  1) Never inject Ctrl+C while the user physically holds Ctrl. Our injection
     ends with a Ctrl KEYUP; with the real key still down the foreground app
     now believes Ctrl is released, so the user's own Ctrl+C does nothing at
     all until they let go and press again. That is the "перехватывает".
  2) Never put the old clipboard back over a write we did not make. If the
     user's Ctrl+C lands inside our capture window, restoring wipes exactly
     what they just copied.
  3) Never restore when our Ctrl+C changed nothing. A pointless text-only
     write still re-owns the clipboard: it cancels Excel's marching ants and
     drops the HTML/RTF/image flavours the user actually had.
"""

from __future__ import annotations

import re
import sys
import threading
import time

import pyperclip

from . import copy_guard, logutil

MARKER_PREFIX = "__bonjur_"
_MARKER_RE = re.compile(r"^\s*" + re.escape(MARKER_PREFIX) + r"[0-9a-fA-F]*__?\s*$")
_CLIP_LOCK = threading.Lock()

_HARD_CAP_S = 5.0
_STABLE_POLLS = 3
_STABLE_GAP_S = 0.04
# a user Ctrl+C this fresh means the clipboard already holds their selection
USER_COPY_S = 1.2


def _clipboard_seq() -> int:
    """Windows clipboard sequence number -- bumps on every write. 0 if unavailable."""
    if sys.platform != "win32":
        return 0
    try:
        import ctypes
        return int(ctypes.windll.user32.GetClipboardSequenceNumber())
    except Exception:  # noqa: BLE001
        return 0


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
    """Crow: while (GetAsyncKeyState(...)) {} -- with timeout so we never hang."""
    if sys.platform != "win32":
        return True
    log = logutil.get()
    t0 = time.perf_counter()
    if not _mods_down_win():
        return True
    log.debug("waiting for modifiers release...")
    while time.perf_counter() - t0 < timeout_s:
        if not _mods_down_win():
            log.debug("modifiers up after %.0fms", (time.perf_counter() - t0) * 1000)
            time.sleep(0.03)
            return True
        time.sleep(0.01)
    log.warning("modifiers still down after %.1fs -- caller must not inject", timeout_s)
    return False


def _send_ctrl_c_win() -> bool:
    """Crow-style: AttachThreadInput + SendInput Ctrl+C.

    Critical fix: AttachThreadInput is required so that SendInput reaches the
    foreground window even when bonjur runs as a background tray process.
    Without it, Windows silently drops the injected keystrokes until the
    process receives real keyboard input (e.g. via a hotkey press).
    This caused the chip to appear only after the first hotkey use.
    Crow Translate (C++) does the same attach/detach around SendInput.
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    log = logutil.get()

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

    # Crow fix: attach our thread to the foreground window input queue
    # so SendInput keystrokes are not silently dropped by Windows.
    attached = False
    fg_tid = 0
    my_tid = 0
    try:
        fg_hwnd = user32.GetForegroundWindow()
        if fg_hwnd:
            fg_tid = int(user32.GetWindowThreadProcessId(fg_hwnd, None))
            my_tid = int(kernel32.GetCurrentThreadId())
            if fg_tid and my_tid and fg_tid != my_tid:
                if user32.AttachThreadInput(my_tid, fg_tid, True):
                    attached = True
                    log.debug("AttachThreadInput %s to %s ok", my_tid, fg_tid)
                else:
                    log.debug("AttachThreadInput %s to %s failed (non-fatal)", my_tid, fg_tid)
    except Exception:  # noqa: BLE001
        logutil.exc("AttachThreadInput setup")

    try:
        arr = (INPUT * 4)(
            key(VK_CONTROL, 0),
            key(VK_C, 0),
            key(VK_C, KEYEVENTF_KEYUP),
            key(VK_CONTROL, KEYEVENTF_KEYUP),
        )
        # tell copy_guard these four events are ours, not a user copy
        with copy_guard.injecting():
            n = user32.SendInput(4, ctypes.byref(arr), ctypes.sizeof(INPUT))
        return int(n) == 4
    except Exception:  # noqa: BLE001
        logutil.exc("SendInput Ctrl+C")
        return False
    finally:
        # Always detach, even if SendInput failed
        if attached:
            try:
                user32.AttachThreadInput(my_tid, fg_tid, False)
            except Exception:  # noqa: BLE001
                pass


def _send_ctrl_c() -> bool:
    if sys.platform == "win32":
        if _send_ctrl_c_win():
            return True
    try:
        import keyboard
        with copy_guard.injecting():
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
    """True for our clipboard probe -- strip whitespace/newlines; prefix is enough."""
    if not text:
        return False
    t = text.strip("\x00").strip()
    if not t:
        return False
    if t.startswith(MARKER_PREFIX):
        if _MARKER_RE.match(t) or t.endswith("__"):
            return True
        if len(t) < 80 and all(c.isalnum() or c in "_-" for c in t):
            return True
    return False


def sanitize_selection(text: str | None) -> str:
    """Strip + drop marker -- call at every boundary (hotkey, watcher, paste)."""
    if not text:
        return ""
    t = text.strip("\x00").strip()
    if not t or _is_marker(t):
        return ""
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


def _restore_verdict(
    previous: str,
    seq_before: int,
    seq_after: int,
    since: float,
    *,
    prev_marker: bool = False,
) -> tuple[bool, str]:
    """Put the old clipboard back only when nothing else has claimed it."""
    if copy_guard.copied_since(since):
        return False, "user copied during capture"
    cur = _clipboard_seq()
    if seq_before and cur and cur == seq_before:
        return False, "clipboard untouched — nothing to put back"
    if seq_after and cur and cur != seq_after:
        return False, "clipboard rewritten by another app"
    if not previous and not prev_marker:
        return False, "previous was empty — never blank a live clipboard"
    return True, ""


def get_selected_text(
    restore_clipboard: bool = True,
    settle_s: float = 1.0,
    *,
    clipboard_fallback: bool = False,
    since: float | None = None,
) -> str:
    """
    Crow-style selection grab via clipboard sequence number (same-text reselect
    safe, never writes a probe to the clipboard). Never raises.

    `since` — perf_counter stamp of the gesture that asked for this capture
    (mouse-up, hotkey press). A user Ctrl+C after that stamp means their own
    copy is already on the clipboard: we read it instead of injecting, and we
    never restore over it.
    """
    log = logutil.get()
    if not _CLIP_LOCK.acquire(timeout=3.0):
        log.warning("get_selected_text: clip lock busy")
        return ""
    try:
        return _get_selected_text_locked(
            restore_clipboard=restore_clipboard,
            settle_s=settle_s,
            clipboard_fallback=clipboard_fallback,
            since=time.perf_counter() if since is None else since,
        )
    finally:
        _CLIP_LOCK.release()


def _get_selected_text_locked(
    *,
    restore_clipboard: bool,
    settle_s: float,
    clipboard_fallback: bool,
    since: float,
) -> str:
    log = logutil.get()
    log.debug(
        "get_selected_text SEQ restore=%s settle=%.2f fallback=%s",
        restore_clipboard, settle_s, clipboard_fallback,
    )

    # FIX (bugs #1 + #3): snapshot AFTER modifiers are released.
    # Old code took `previous` and `seq_before` BEFORE _wait_mods_up().
    # If the user pressed Ctrl+C/X during the up-to-2s wait, their real
    # copy landed on the clipboard but `previous` still held stale text.
    # On restore we wiped the user's copy -- the "floating" paste bug.
    # Also `seq_before` went stale during the wait, causing false-positive
    # "clipboard changed" detection from unrelated writes.

    previous = ""
    try:
        # The user pressed Ctrl+C themselves after the gesture -- their
        # selection is already on the clipboard. Reading it is faster than
        # injecting, and touching nothing means their copy survives intact.
        if copy_guard.copied_since(since) and copy_guard.recent(USER_COPY_S):
            time.sleep(0.06)  # let the target app finish writing
            own = sanitize_selection(_clip_get())
            if own:
                log.info("user Ctrl+C in flight -- reuse clipboard len=%s", len(own))
                return own

        # Never inject while a modifier is physically held: our trailing
        # Ctrl KEYUP would desync the foreground app and swallow the user's
        # own Ctrl+C until they release and press again.
        if not _wait_mods_up(2.0):
            log.warning("modifiers stuck down -- skip injecting Ctrl+C")
            if clipboard_fallback:
                return sanitize_selection(_clip_get())
            return ""

        # Snapshot clipboard NOW -- modifiers are up, no user Ctrl+C/X race.
        try:
            previous = _clip_get()
        except Exception:  # noqa: BLE001
            logutil.exc("clip previous")
        prev_marker = _is_marker(previous)
        if prev_marker:
            previous = ""  # a probe from an ancient build — wipe, never re-serve
        log.debug("clip previous len=%s head=%r", len(previous), previous[:80])

        # Sequence number taken right before Ctrl+C -- no stale gap.
        seq_before = _clipboard_seq()

        if not _send_ctrl_c():
            log.warning("Ctrl+C send failed")
            if clipboard_fallback and previous:
                return sanitize_selection(previous)
            return ""

        # Wait for the clipboard to change.
        soft = max(float(settle_s), 0.25)
        hard = max(soft, min(_HARD_CAP_S, soft * 4.0 if soft < 2 else _HARD_CAP_S))
        deadline_soft = time.perf_counter() + soft
        deadline_hard = time.perf_counter() + hard
        polls = 0
        selected = ""
        seq_after = 0
        while time.perf_counter() < deadline_hard:
            time.sleep(0.03)
            polls += 1

            if seq_before:
                if _clipboard_seq() == seq_before:
                    if time.perf_counter() > deadline_soft:
                        break
                    continue
            try:
                got = _clip_get()
            except Exception:  # noqa: BLE001
                continue
            if not got:
                if time.perf_counter() > deadline_soft:
                    break
                continue
            if not seq_before and got == previous:
                if time.perf_counter() > deadline_soft:
                    break
                continue

            # Real content -- wait until length stabilizes (large blobs).
            candidate = got
            stable = 1
            last_len = len(candidate)
            for _ in range(_STABLE_POLLS - 1):
                time.sleep(_STABLE_GAP_S)
                try:
                    again = _clip_get()
                except Exception:  # noqa: BLE001
                    break
                if not again:
                    break
                if len(again) == last_len and again == candidate:
                    stable += 1
                else:
                    candidate = again
                    last_len = len(again)
                    stable = 1
            if stable < 2 and last_len > 50_000:
                time.sleep(0.08)
                try:
                    again = _clip_get()
                    if again:
                        candidate = again
                except Exception:  # noqa: BLE001
                    pass

            selected = sanitize_selection(candidate)
            if selected:
                seq_after = _clipboard_seq()
                log.debug("clip changed after %s polls len=%s", polls, len(selected))
                break

        if restore_clipboard:
            ok, why = _restore_verdict(
                previous, seq_before, seq_after, since, prev_marker=prev_marker
            )
            if ok:
                _clip_set(previous)
            else:
                log.info("clipboard left as is: %s", why)

        selected = sanitize_selection(selected)
        if selected:
            log.info("selected ok len=%s head=%r", len(selected), selected[:100])
            return selected

        if clipboard_fallback and previous and not _is_marker(previous):
            fb = sanitize_selection(previous)
            if fb:
                log.info("empty selection -> fallback previous len=%s", len(fb))
                return fb

        log.warning("selection empty polls=%s", polls)
        return ""
    except Exception:  # noqa: BLE001
        logutil.exc("get_selected_text fatal")
        try:
            if restore_clipboard and previous and not copy_guard.copied_since(since):
                _clip_set(previous)
        except Exception:  # noqa: BLE001
            pass
        if clipboard_fallback and previous and not _is_marker(previous):
            return sanitize_selection(previous)
        return ""