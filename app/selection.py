"""Selection capture — silent first, Crow Ctrl+C only as a last resort.

Primary path (chip + hotkey):
  app/silent_selection.py reads the selection via Edit/RichEdit/Scintilla
  messages and UI Automation TextPattern.GetSelection(). No clipboard
  write, no keystrokes, no race with ShareX / Caramba / AHK / the user's
  own Ctrl+C.

Fallback (hotkey only, allow_inject=True):
  Crow Translate Windows approach (selection.cpp):
    1) snapshot clipboard
    2) wait until Win/Shift/Alt/Ctrl are ALL unpressed
    3) SendInput / WM_COPY
    4) wait for clipboard change (up to ~1s)
    5) read text, restore clipboard

The chip watcher MUST call get_selected_text(allow_inject=False). A missed
chip is better than a stolen paste. Fake Ctrl+C on every mouse-drag is what
made "скопировал — вставилось прошлое" and phantom keypresses.

Change detection on the inject path: GetClipboardSequenceNumber().

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

from . import clip_formats, copy_guard, input_arbiter, logutil

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


def _send_ctrl_c_win() -> bool | None:
    """Crow-style: AttachThreadInput + SendInput Ctrl+C.

    Returns True on success, False when nothing was injected (caller may retry
    another way), None when we injected part of the sequence and must not.

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

    # A lock screen (or a TimeWatcher series) owns the keyboard. Injecting into
    # it types our Ctrl+C into whatever is behind it and, worse, our trailing
    # Ctrl KEYUP desyncs the modifier state of the app that does have focus.
    # See MemPalace general/input-arbiter.
    if input_arbiter.busy():
        log.info("input is held by another app — not injecting Ctrl+C")
        return False

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_SCANCODE = 0x0008
    MAPVK_VK_TO_VSC = 0
    VK_CONTROL = 0x11
    VK_C = 0x43
    WM_COPY = 0x0301

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

    class GUITHREADINFO(ctypes.Structure):
        _fields_ = (
            ("cbSize", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("hwndActive", wintypes.HWND),
            ("hwndFocus", wintypes.HWND),
            ("hwndCapture", wintypes.HWND),
            ("hwndMenuOwner", wintypes.HWND),
            ("hwndMoveSize", wintypes.HWND),
            ("hwndCaret", wintypes.HWND),
            ("rcCaret", wintypes.RECT),
        )

    def key(vk: int, flags: int = 0, *, scancode_flag: bool = False) -> INPUT:
        scan = int(user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC) & 0xFF)
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        fl = flags | (KEYEVENTF_SCANCODE if scancode_flag else 0)
        inp.union.ki = KEYBDINPUT(vk, scan, fl, 0, None)
        return inp

    def send(*events: INPUT) -> int:
        arr = (INPUT * len(events))(*events)
        return int(user32.SendInput(len(events), ctypes.byref(arr), ctypes.sizeof(INPUT)))

    def ctrl_is_down() -> bool:
        return bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)

    def force_ctrl_up() -> None:
        try:
            send(key(VK_CONTROL, KEYEVENTF_KEYUP, scancode_flag=False))
        except Exception:  # noqa: BLE001
            pass
        try:
            send(key(VK_CONTROL, KEYEVENTF_KEYUP, scancode_flag=True))
        except Exception:  # noqa: BLE001
            pass

    def focus_hwnd(fg: int, tid: int) -> int:
        try:
            if tid:
                info = GUITHREADINFO()
                info.cbSize = ctypes.sizeof(GUITHREADINFO)
                if user32.GetGUIThreadInfo(tid, ctypes.byref(info)) and info.hwndFocus:
                    return int(info.hwndFocus)
        except Exception:  # noqa: BLE001
            pass
        try:
            h = int(user32.GetFocus() or 0)
            if h:
                return h
        except Exception:  # noqa: BLE001
            pass
        return int(fg or 0)

    def try_wm_copy(hwnd: int, seq0: int) -> bool:
        """Copy without keystrokes — cannot type stray c into the document."""
        if not hwnd:
            return False
        try:
            user32.SendMessageW(hwnd, WM_COPY, 0, 0)
        except Exception:  # noqa: BLE001
            logutil.exc("WM_COPY")
            return False
        for _ in range(10):  # ~100ms
            time.sleep(0.01)
            try:
                if seq0 and _clipboard_seq() != seq0:
                    seq1 = _clipboard_seq()
                    got_len = len((_clip_get() or "").strip())
                    log.info(
                        "wm_copy ok hwnd=%s seq %s→%s clip_len=%s",
                        hwnd,
                        seq0,
                        seq1,
                        got_len,
                    )
                    return True
            except Exception:  # noqa: BLE001
                break
        log.debug("wm_copy no clipboard change hwnd=%s", hwnd)
        return False

    attached = False
    fg_tid = 0
    my_tid = 0
    fg_hwnd = 0
    try:
        from . import diag, peers

        peers.log_snapshot("inject peers")
        fg = diag.foreground()
        if fg:
            log.info(
                "inject fg exe=%r pid=%s layout=%s title=%r",
                fg.exe,
                fg.pid,
                fg.layout,
                fg.title,
            )
    except Exception:  # noqa: BLE001
        pass
    try:
        fg_hwnd = int(user32.GetForegroundWindow() or 0)
        if fg_hwnd:
            fg_tid = int(user32.GetWindowThreadProcessId(fg_hwnd, None))
            my_tid = int(kernel32.GetCurrentThreadId())
            if fg_tid and my_tid and fg_tid != my_tid:
                if user32.AttachThreadInput(my_tid, fg_tid, True):
                    attached = True
                    log.debug("AttachThreadInput %s to %s ok", my_tid, fg_tid)
                else:
                    log.warning(
                        "AttachThreadInput %s to %s FAILED — chip/grab may miss",
                        my_tid,
                        fg_tid,
                    )
    except Exception:  # noqa: BLE001
        logutil.exc("AttachThreadInput setup")

    # Prefer WM_COPY: SendInput still typed c into Firefox contenteditable in 2.2.1
    # (AUTO_CATCH raw=cInturristo while ctrl_confirmed=1).
    seq0 = _clipboard_seq()
    target = focus_hwnd(fg_hwnd, fg_tid)
    if try_wm_copy(target, seq0):
        if attached:
            try:
                user32.AttachThreadInput(my_tid, fg_tid, False)
            except Exception:  # noqa: BLE001
                pass
        return True
    if fg_hwnd and fg_hwnd != target and try_wm_copy(fg_hwnd, seq0):
        if attached:
            try:
                user32.AttachThreadInput(my_tid, fg_tid, False)
            except Exception:  # noqa: BLE001
                pass
        return True

    log.info("wm_copy miss — falling back to SendInput Ctrl+C")

    ctrl_down = False
    try:
        with copy_guard.injecting(tail_s=0.25):
            if send(key(VK_CONTROL, 0)) != 1:
                log.warning("SendInput refused Ctrl down")
                return False
            ctrl_down = True

            for _ in range(12):
                if ctrl_is_down():
                    break
                time.sleep(0.003)
            else:
                log.warning(
                    "Ctrl never registered as down — not tapping C "
                    "(would type stray «с» on RU layout)"
                )
                return None

            if not ctrl_is_down():
                log.warning("Ctrl dropped before C tap — aborting (stray-c guard)")
                return None

            if send(key(VK_C, 0), key(VK_C, KEYEVENTF_KEYUP)) != 2:
                log.warning("SendInput refused C")
                return None
            still = ctrl_is_down()
            log.debug(
                "inject Ctrl+C fallback ok still_down=%s",
                int(still),
            )
        return True
    except Exception:  # noqa: BLE001
        logutil.exc("SendInput Ctrl+C")
        return None if ctrl_down else False
    finally:
        if ctrl_down:
            try:
                with copy_guard.injecting(tail_s=0.25):
                    force_ctrl_up()
            except Exception:  # noqa: BLE001
                logutil.exc("SendInput Ctrl up")
        if attached:
            try:
                user32.AttachThreadInput(my_tid, fg_tid, False)
            except Exception:  # noqa: BLE001
                pass


def _send_ctrl_c() -> bool:
    if sys.platform == "win32":
        res = _send_ctrl_c_win()
        if res:
            return True
        if res is None:
            # Keys already went out. A second attempt through `keyboard` would
            # double the injection — that is how a lone «с» gets typed.
            return False
    if input_arbiter.busy():
        return False
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
    """Strip + drop marker + peel stray leading c/с from field bug #1."""
    if not text:
        return ""
    t = text.strip("\x00").strip()
    if not t or _is_marker(t):
        return ""
    first = t.splitlines()[0].strip() if t else ""
    if _is_marker(first) and len(t) < 100:
        return ""
    # Field: inject typed a lone c/с into the selection (cInturristo). Peel it
    # so chip/translate see the real word; auto_catch still sees the raw form.
    try:
        from . import auto_catch

        reason = auto_catch.looks_stray_c(t)
        if reason == "lone_c":
            return ""
        if reason and reason.startswith("prefix_c+") and len(t) >= 2:
            t = t[1:].lstrip()
    except Exception:  # noqa: BLE001
        pass
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
    # Non-text guard: ShareX/Greenshot/Explorer put an IMAGE (CF_DIB) or FILES
    # (CF_HDROP) on the clipboard. pyperclip cannot see them, so `selected` is
    # empty and seq_after is 0 -- the old code then wrote stale TEXT back over
    # the image and the user pasted yesterday's text. Never restore over non-text.
    try:
        if clip_formats.non_text_present():
            return False, "non-text on clipboard (image/files) -- keep it"
    except Exception:  # noqa: BLE001
        pass
    if copy_guard.copied_since(since):
        return False, "user copied during capture"
    cur = _clipboard_seq()
    if seq_before and cur and cur == seq_before:
        # After pre-clear the clipboard is empty; a failed copy leaves it empty.
        # Always restore previous in that case (rich formats live in `previous`).
        if previous or prev_marker:
            return True, "capture failed after pre-clear — restore previous"
        return False, "clipboard untouched — nothing to put back"
    if seq_after and cur and cur != seq_after:
        return False, "clipboard rewritten by another app"
    if not previous and not prev_marker:
        return False, "previous was empty — never blank a live clipboard"
    return True, ""


def _try_silent() -> str:
    """Read the selection without clipboard or keystrokes. Never raises."""
    try:
        from . import silent_selection

        return sanitize_selection(silent_selection.read())
    except Exception:  # noqa: BLE001
        logutil.exc("silent selection")
        return ""


def get_selected_text(
    restore_clipboard: bool = True,
    settle_s: float = 1.0,
    *,
    clipboard_fallback: bool = False,
    since: float | None = None,
    allow_inject: bool = True,
) -> str:
    """
    Grab the current selection. Never raises.

    Silent UIA/native first. The Crow clipboard inject runs only when
    `allow_inject` is True (hotkey). The chip watcher must pass False.
    """
    log = logutil.get()
    stamp = time.perf_counter() if since is None else since

    # The user pressed Ctrl+C themselves after the gesture -- their
    # selection is already on the clipboard. Reading it is faster than
    # injecting, and touching nothing means their copy survives intact.
    if copy_guard.copied_since(stamp) and copy_guard.recent(USER_COPY_S):
        time.sleep(0.06)  # let the target app finish writing
        own = sanitize_selection(_clip_get())
        if own:
            log.info("user Ctrl+C in flight -- reuse clipboard len=%s", len(own))
            return own

    silent = _try_silent()
    if silent:
        log.info("silent selection len=%s head=%r", len(silent), silent[:100])
        return silent

    if not allow_inject:
        log.info("silent miss — not injecting (watcher / allow_inject=0)")
        return ""

    if not _CLIP_LOCK.acquire(timeout=3.0):
        log.warning("get_selected_text: clip lock busy")
        return ""
    deferred: list[tuple] = []
    try:
        text = _get_selected_text_locked(
            restore_clipboard=restore_clipboard,
            settle_s=settle_s,
            clipboard_fallback=clipboard_fallback,
            since=stamp,
            deferred_auto=deferred,
        )
    finally:
        _CLIP_LOCK.release()
    # Auto reports OUTSIDE the clip lock — reading bonjur.log under the lock
    # froze the session (pythonw Responding=False) in the 2.2.0 field run.
    for item in deferred:
        try:
            kind = item[0]
            if kind == "stray":
                from . import auto_catch

                auto_catch.note_stray_selection(item[1], reason=item[2])
            elif kind == "empty":
                from . import auto_catch

                auto_catch.note_empty_capture(polls=item[1], previous_head=item[2])
        except Exception:  # noqa: BLE001
            logutil.exc("deferred auto_catch")
    return text


def _get_selected_text_locked(
    *,
    restore_clipboard: bool,
    settle_s: float,
    clipboard_fallback: bool,
    since: float,
    deferred_auto: list | None = None,
) -> str:
    log = logutil.get()
    deferred_auto = deferred_auto if deferred_auto is not None else []
    log.debug(
        "get_selected_text INJECT restore=%s settle=%.2f fallback=%s",
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

        # Firefox skips clipboard write when selection text already equals the
        # clipboard (same-sentence re-select). Pre-clear so a successful copy
        # always bumps the sequence number. Empty string only — restored after.
        # BUT never pre-clear when the clipboard holds an IMAGE/FILES (ShareX
        # auto-copy image, Explorer copy): wiping it would destroy the user's
        # screenshot. We still inject Ctrl+C so text selection captures + chip
        # shows; _restore_verdict guards against restoring text over non-text.
        # Product rule: TEXT selection -> chip; a SCREENSHOT/image -> stays
        # ready to paste. Save the image before Ctrl+C; if the copy yields
        # text we show the chip, if not we put the saved image back.
        saved_image_dib = None
        nontext_before = False
        try:
            nontext_before = clip_formats.non_text_present()
            if nontext_before:
                saved_image_dib = clip_formats.get_image_dib()
        except Exception:  # noqa: BLE001
            pass
        if nontext_before:
            log.info(
                "clipboard holds non-text (%s) — saved image=%s, skip pre-clear",
                clip_formats.describe(),
                "yes" if saved_image_dib else "no",
            )
        elif not _clip_set(""):
            log.warning("clipboard pre-clear failed — same-text reselect may miss")
        else:
            log.debug("clipboard pre-cleared (same-text reselect guard)")

        # Sequence number taken right before Ctrl+C / WM_COPY -- after pre-clear.
        seq_before = _clipboard_seq()
        sharex_clip = "ShareX" in (previous or "") and "Screenshots" in (previous or "")
        if sharex_clip:
            log.info("sharex_clip=1 previous looks like ShareX screenshot path")

        if not _send_ctrl_c():
            log.warning("Ctrl+C send failed")
            if restore_clipboard and previous:
                _clip_set(previous)
            if clipboard_fallback and previous:
                return sanitize_selection(previous)
            return ""

        def _wait_for_change(soft_s: float, hard_s: float) -> tuple[str, int, int]:
            """Poll until clipboard changes. Returns (selected, seq_after, polls)."""
            deadline_soft = time.perf_counter() + soft_s
            deadline_hard = time.perf_counter() + hard_s
            polls_local = 0
            selected_local = ""
            seq_after_local = 0
            while time.perf_counter() < deadline_hard:
                time.sleep(0.03)
                polls_local += 1

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

                # Detect stray BEFORE sanitize; report after clip lock is released.
                raw = (candidate or "").strip("\x00").strip()
                try:
                    from . import auto_catch

                    reason = auto_catch.looks_stray_c(raw)
                    if reason:
                        deferred_auto.append(("stray", raw, reason))
                except Exception:  # noqa: BLE001
                    pass

                selected_local = sanitize_selection(candidate)
                if selected_local:
                    seq_after_local = _clipboard_seq()
                    log.debug(
                        "clip changed after %s polls len=%s",
                        polls_local,
                        len(selected_local),
                    )
                    break
            return selected_local, seq_after_local, polls_local

        # Wait for the clipboard to change.
        soft = max(float(settle_s), 0.25)
        hard = max(soft, min(_HARD_CAP_S, soft * 4.0 if soft < 2 else _HARD_CAP_S))
        selected, seq_after, polls = _wait_for_change(soft, hard)

        # One retry when inject claimed ok but clipboard never moved (ShareX/FF race).
        try:
            still_untouched = (
                not selected
                and bool(seq_before)
                and _clipboard_seq() == seq_before
                and not copy_guard.copied_since(since)
            )
        except Exception:  # noqa: BLE001
            still_untouched = False
        if still_untouched:
            log.info("clipboard untouched — retry Ctrl+C once sharex_clip=%s", int(sharex_clip))
            time.sleep(0.08)
            if _send_ctrl_c():
                selected, seq_after, polls2 = _wait_for_change(
                    min(soft, 0.8), min(hard, 1.6)
                )
                polls += polls2
                if selected:
                    log.info("retry capture ok len=%s", len(selected))

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

        # Successful inject path but nothing landed — classic no-chip race
        # (ShareX holding clipboard was the field signature).
        try:
            clip_untouched = bool(seq_before) and _clipboard_seq() == seq_before
        except Exception:  # noqa: BLE001
            clip_untouched = not selected and not seq_after
        if clip_untouched:
            deferred_auto.append(("empty", polls, (previous or "")[:80]))

        if clipboard_fallback and previous and not _is_marker(previous):
            fb = sanitize_selection(previous)
            if fb:
                log.info("empty selection -> fallback previous len=%s", len(fb))
                return fb

        # No text captured -> this was a screenshot / non-text gesture.
        # Put the saved image back so it stays ready to paste (owner rule).
        if saved_image_dib:
            if clip_formats.set_image_dib(saved_image_dib):
                log.info("no text -> restored saved image to clipboard")
            else:
                log.warning("no text -> failed to restore saved image")
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