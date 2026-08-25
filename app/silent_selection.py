"""Read the current text selection without touching the clipboard.

The Crow Ctrl+C path races every other clipboard/keyboard hook on the
machine (ShareX, Caramba, AHK, the user's own copy). This module is the
way out: native Edit/RichEdit/Scintilla messages, then UI Automation
TextPattern.GetSelection(). Read-only. No SendInput, no WM_COPY, no
pre-clear.

Used by get_selected_text() before any inject. The chip watcher must
never fall back to inject — a missed chip is better than a stolen paste.

Native messages run on the caller thread (no COM). UIA lives on one
long-lived STA worker that pumps messages — a blocking STA thread
deadlocks CoCreateInstance / cross-process UIA.

GetSelection returns IUIAutomationTextRangeArray, NOT a SAFEARRAY.
Treating the pointer as a SAFEARRAY is what blew up Chrome (first as
OverflowError on 64-bit PSA, then DISP_E_BADINDEX).
"""

from __future__ import annotations

import ctypes
import queue
import sys
import threading
import time
from ctypes import wintypes

from . import logutil

MAX_CHARS = 16_000

WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
EM_GETSEL = 0x00B0
WM_USER = 0x0400
EM_EXGETSEL = WM_USER + 52
EM_GETTEXTRANGE = WM_USER + 75
SCI_GETSELTEXT = 2161
PM_REMOVE = 0x0001

COINIT_APARTMENTTHREADED = 0x2
CLSCTX_INPROC_SERVER = 0x1
S_OK = 0
S_FALSE = 1
RPC_E_CHANGED_MODE = 0x80010106

UIA_TextPatternId = 10014

_tls = threading.local()
_UIA_TIMEOUT_S = 1.4

_user32_mod = ctypes.WinDLL("user32", use_last_error=True)
_oleaut32_mod = ctypes.WinDLL("oleaut32", use_last_error=True)
_SendMessageTimeoutW = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    wintypes.HWND,
    wintypes.UINT,
    ctypes.c_size_t,
    ctypes.c_ssize_t,
    ctypes.c_uint,
    ctypes.c_uint,
    ctypes.POINTER(ctypes.c_size_t),
)(("SendMessageTimeoutW", _user32_mod))
SMTO_ABORTIFHUNG = 0x0002
SEND_TIMEOUT_MS = 200
_SysFreeString = ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(
    ("SysFreeString", _oleaut32_mod)
)


class GUID(ctypes.Structure):
    _fields_ = (
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    )


class POINT(ctypes.Structure):
    _fields_ = (("x", ctypes.c_long), ("y", ctypes.c_long))


class CHARRANGE(ctypes.Structure):
    _fields_ = (("cpMin", ctypes.c_long), ("cpMax", ctypes.c_long))


class TEXTRANGEW(ctypes.Structure):
    _fields_ = (("chrg", CHARRANGE), ("lpstrText", ctypes.c_void_p))


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


def _guid(d1: int, d2: int, d3: int, d4: bytes) -> GUID:
    g = GUID()
    g.Data1 = d1
    g.Data2 = d2
    g.Data3 = d3
    for i, b in enumerate(d4):
        g.Data4[i] = b
    return g


_CLSID_UIA = _guid(0xFF48DBA4, 0x60EF, 0x4201, b"\xAA\x87\x54\x10\x3E\xEF\x59\x4E")
_IID_UIA = _guid(0x30CBE57D, 0xD9D0, 0x452A, b"\xAB\x13\x7A\xC5\xAC\x48\x25\xEE")
_IID_TEXT = _guid(0x32EBA289, 0x3583, 0x42C9, b"\x9C\x59\x3B\x6D\x9A\x1E\x9B\x6A")


def read() -> str:
    """Current selection, or "" if we cannot see one. Never raises."""
    if sys.platform != "win32":
        return ""
    return _read_both(None)


def read_hwnd(hwnd: int) -> str:
    """Same as read(), but pinned to a window. For tests / diagnostics."""
    if sys.platform != "win32" or not hwnd:
        return ""
    return _read_both(int(hwnd))


def warm() -> None:
    """Nudge the accessibility tree awake. Called at mouse-DOWN so Chromium
    has the whole drag to build it, instead of us paying for the cold probe
    at mouse-UP when the user is already waiting for a chip."""
    if sys.platform != "win32":
        return
    try:
        _worker.warm()
    except Exception:  # noqa: BLE001
        pass


def _read_both(hwnd: int | None) -> str:
    try:
        text = _read_native(hwnd)
        if text:
            logutil.get().debug("silent native len=%s", len(text))
            return _clip(text)
    except Exception:  # noqa: BLE001
        logutil.exc("silent native")
    # An Edit/Scintilla with no range is "nothing selected", not "try UIA"
    # (UIA often returns the whole document).
    if hwnd:
        cls = _class_name(int(hwnd))
        if _looks_edit(cls) or "combo" in cls.lower():
            return ""
    try:
        text = _worker.submit(hwnd)
        if text:
            # hwnd+class on the hit line too: without it a log shows which
            # gestures missed but not which window class they hit, and the
            # cold-tree pattern (first probe of an HWND misses, the rest hit)
            # is invisible.
            hit = int(hwnd or _focus_hwnd() or 0)
            logutil.get().debug(
                "silent uia len=%s hwnd=%s class=%r", len(text), hit, _class_name(hit)
            )
            return _clip(text)
    except Exception:  # noqa: BLE001
        logutil.exc("silent uia")
    try:
        target = int(hwnd or _focus_hwnd() or 0)
        logutil.get().debug("silent miss hwnd=%s class=%r", target, _class_name(target))
    except Exception:  # noqa: BLE001
        pass
    return ""


def _clip(text: str) -> str:
    t = (text or "").replace("\x00", "")
    if len(t) > MAX_CHARS:
        t = t[:MAX_CHARS]
    return t


def _ok(hr: int) -> bool:
    return (int(hr) & 0x80000000) == 0


def _send(hwnd: int, msg: int, wparam: int = 0, lparam: int = 0) -> int:
    """SendMessage with a deadline. A bare SendMessageW to a hung foreign UI
    thread blocks forever, so _capture_and_fire's finally never runs and
    _busy stays True — the chip is then dead for the rest of the process."""
    res = ctypes.c_size_t(0)
    ok = _SendMessageTimeoutW(
        int(hwnd),
        int(msg),
        int(wparam),
        int(lparam),
        SMTO_ABORTIFHUNG,
        SEND_TIMEOUT_MS,
        ctypes.byref(res),
    )
    return int(res.value) if ok else 0


def _ptr(obj: ctypes.Structure | ctypes.Array) -> int:
    return int(ctypes.addressof(obj))


# --- native Edit / RichEdit / Scintilla ------------------------------------

def _user32():
    return _user32_mod


def _focus_hwnd() -> int:
    user32 = _user32()
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    fg = int(user32.GetForegroundWindow() or 0)
    tid = int(user32.GetWindowThreadProcessId(fg, None) or 0) if fg else 0
    if tid and user32.GetGUIThreadInfo(tid, ctypes.byref(info)):
        hwnd = int(info.hwndFocus or info.hwndActive or fg or 0)
        if hwnd:
            return hwnd
    return fg


def _class_name(hwnd: int) -> str:
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    try:
        _user32().GetClassNameW(hwnd, buf, 256)
    except Exception:  # noqa: BLE001
        return ""
    return buf.value or ""


def _looks_edit(cls: str) -> bool:
    c = (cls or "").lower()
    return any(h in c for h in ("edit", "richedit", "scintilla", "textfield", "textarea"))


def _read_native(hwnd: int | None = None) -> str:
    target = int(hwnd or _focus_hwnd() or 0)
    if not target:
        return ""
    cls = _class_name(target)
    if "combo" in cls.lower():
        child = int(_user32().FindWindowExW(target, 0, "Edit", None) or 0)
        if child:
            target, cls = child, _class_name(child)
    if "scintilla" in cls.lower():
        got = _read_scintilla(target)
        if got:
            return got
    return _read_edit(target, cls)


def _edit_bounds(hwnd: int) -> tuple[int, int]:
    start = wintypes.DWORD(0)
    end = wintypes.DWORD(0)
    _send(hwnd, EM_GETSEL, _ptr(start), _ptr(end))
    a, b = int(start.value), int(end.value)
    if b > a:
        return a, b
    cr = CHARRANGE()
    _send(hwnd, EM_EXGETSEL, 0, _ptr(cr))
    return int(cr.cpMin), int(cr.cpMax)


def _read_edit(hwnd: int, cls: str = "") -> str:
    a, b = _edit_bounds(hwnd)
    if b <= a or (b - a) > 1_000_000:
        return ""
    length = _send(hwnd, WM_GETTEXTLENGTH, 0, 0)
    if length <= 0:
        return _read_richedit_range(hwnd, a, b)
    n = min(length, 1_000_000) + 1
    buf = ctypes.create_unicode_buffer(n)
    _send(hwnd, WM_GETTEXT, n, _ptr(buf))
    text = buf.value or ""
    # Two offset domains. RichEdit stores a line break as one CR, so
    # EM_GETSEL counts 1 per break, but WM_GETTEXT hands back CRLF.
    # Slicing one with the other shifts left by the number of preceding
    # breaks: "WORLD" on line 3 came out as '\r\nWOR'. Plain EDIT has no
    # such split, hence the class check.
    if "rich" in (cls or "").lower():
        text = text.replace("\r\n", "\r")
    if not text:
        return _read_richedit_range(hwnd, a, b)
    if a >= len(text):
        return _read_richedit_range(hwnd, a, b)
    return text[a:min(b, len(text))]


def _read_richedit_range(hwnd: int, start: int, end: int) -> str:
    n = end - start
    if n <= 0 or n > 1_000_000:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    tr = TEXTRANGEW()
    tr.chrg.cpMin = start
    tr.chrg.cpMax = end
    tr.lpstrText = ctypes.cast(buf, ctypes.c_void_p)
    if _send(hwnd, EM_GETTEXTRANGE, 0, _ptr(tr)) <= 0:
        return ""
    return buf.value or ""


def _read_scintilla(hwnd: int) -> str:
    n = _send(hwnd, SCI_GETSELTEXT, 0, 0)
    if n <= 1:
        return ""
    n = min(n, MAX_CHARS + 1)
    buf = ctypes.create_string_buffer(n)
    _send(hwnd, SCI_GETSELTEXT, 0, _ptr(buf))
    raw = buf.raw[: max(0, n - 1)].rstrip(b"\x00")
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", "replace")


# --- STA worker + message pump --------------------------------------------

def _pump() -> None:
    msg = wintypes.MSG()
    peek = _user32_mod.PeekMessageW
    translate = _user32_mod.TranslateMessage
    dispatch = _user32_mod.DispatchMessageW
    while peek(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
        translate(ctypes.byref(msg))
        dispatch(ctypes.byref(msg))


class _StaWorker:
    def __init__(self) -> None:
        self._q: queue.Queue[tuple[int | None, queue.Queue[str] | None]] = queue.Queue()
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, name="bonjur-silent", daemon=True
        )
        self._started = False
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._thread.start()
            self._started = True
        self._ready.wait(timeout=1.0)

    def submit(self, hwnd: int | None) -> str:
        self.start()
        reply: queue.Queue[str] = queue.Queue(maxsize=1)
        self._q.put((hwnd, reply))
        try:
            return reply.get(timeout=_UIA_TIMEOUT_S)
        except queue.Empty:
            logutil.get().warning("silent uia timeout hwnd=%s", hwnd)
            return ""

    def warm(self) -> None:
        """Fire-and-forget probe. reply=None marks it single-shot: nobody is
        waiting, so it must not occupy the worker on the retry loop."""
        self.start()
        self._q.put((None, None))

    def _loop(self) -> None:
        _ensure_com()
        self._ready.set()
        while True:
            try:
                hwnd, reply = self._q.get(timeout=0.05)
            except queue.Empty:
                _pump()
                continue
            text = ""
            try:
                text = _read_uia(hwnd) or ""
                if reply is None:  # warm probe — one shot, no waiter
                    _pump()
                    continue
                # A cold Chromium a11y tree answers empty *and fast*: the
                # first probe only flips AXMode on and IPCs the renderer.
                # Field logs show zero UIA timeouts and every genuine Chrome
                # miss being the first probe of that HWND — so keep asking
                # inside the 1.4 s submit() already waits for.
                tries = 1
                deadline = time.perf_counter() + 1.1
                delay = 0.05
                while not text and time.perf_counter() + delay < deadline:
                    time.sleep(delay)
                    _pump()
                    text = _read_uia(hwnd) or ""
                    tries += 1
                    delay = min(delay * 2, 0.3)
                logutil.get().debug("silent uia tries=%s len=%s", tries, len(text))
            except Exception:  # noqa: BLE001
                logutil.exc("silent uia worker")
            if reply is None:
                _pump()
                continue
            try:
                reply.put_nowait(text)
            except Exception:  # noqa: BLE001
                pass
            _pump()


_worker = _StaWorker()


# --- UI Automation ---------------------------------------------------------

def _vtbl(this: int, idx: int, *argtypes, restype=ctypes.c_long):
    """restype is c_long, not HRESULT — failed codes must not raise OSError."""
    vtbl = ctypes.cast(ctypes.c_void_p(this), ctypes.POINTER(ctypes.c_void_p))[0]
    fptr = ctypes.cast(ctypes.c_void_p(vtbl), ctypes.POINTER(ctypes.c_void_p))[idx]
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(fptr)


def _release(this: int | None) -> None:
    if not this:
        return
    try:
        _vtbl(this, 2, restype=ctypes.c_ulong)(this)
    except Exception:  # noqa: BLE001
        pass


def _ensure_com() -> bool:
    if getattr(_tls, "ok", False):
        return True
    try:
        ole32 = ctypes.windll.ole32
        ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        ole32.CoInitializeEx.restype = ctypes.HRESULT
        hr = int(ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)) & 0xFFFFFFFF
        if hr not in (S_OK, S_FALSE, RPC_E_CHANGED_MODE):
            return False
        _tls.ok = True
        return True
    except Exception:  # noqa: BLE001
        return False


def _factory() -> int:
    fac = int(getattr(_tls, "factory", 0) or 0)
    if fac:
        return fac
    if not _ensure_com():
        return 0
    ole32 = ctypes.windll.ole32
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(GUID),
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = ctypes.HRESULT
    punk = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(
        ctypes.byref(_CLSID_UIA),
        None,
        CLSCTX_INPROC_SERVER,
        ctypes.byref(_IID_UIA),
        ctypes.byref(punk),
    )
    if not _ok(hr) or not punk.value:
        logutil.get().warning("CUIAutomation create failed hr=0x%08X", int(hr) & 0xFFFFFFFF)
        return 0
    fac = int(punk.value)
    _tls.factory = fac
    return fac


def _read_uia(hwnd: int | None = None) -> str:
    uia = _factory()
    if not uia:
        return ""
    seen: set[int] = set()
    cands = _candidate_elements(uia, hwnd)
    for el in cands:
        if not el or el in seen:
            continue
        seen.add(el)
        try:
            text = _safe_selection(el)
            if text:
                # cand count separates "no element to ask" from "asked and
                # got nothing" — they look identical from _read_both.
                logutil.get().debug("silent uia hit cand=%s", len(cands))
                return text
            parent = _parent(uia, el)
            hops = 0
            while parent and hops < 6:
                if parent not in seen:
                    seen.add(parent)
                    text = _safe_selection(parent)
                    if text:
                        _release(parent)
                        return text
                nxt = _parent(uia, parent)
                _release(parent)
                parent = nxt
                hops += 1
        finally:
            _release(el)
    return ""


def _safe_selection(el: int) -> str:
    try:
        return _selection_from_element(el)
    except Exception:  # noqa: BLE001
        logutil.get().debug("silent uia element failed", exc_info=True)
        return ""


def _candidate_elements(uia: int, hwnd: int | None) -> list[int]:
    out: list[int] = []
    if hwnd:
        from_hwnd = _from_handle(uia, int(hwnd))
        if from_hwnd:
            out.append(from_hwnd)
        return out
    focused = _get_focused(uia)
    if focused:
        out.append(focused)
    fg = _focus_hwnd()
    if fg:
        from_hwnd = _from_handle(uia, fg)
        if from_hwnd:
            out.append(from_hwnd)
    pt = POINT()
    try:
        _user32().GetCursorPos(ctypes.byref(pt))
        from_pt = _from_point(uia, pt)
        if from_pt:
            out.append(from_pt)
    except Exception:  # noqa: BLE001
        pass
    return out


def _get_focused(uia: int) -> int:
    el = ctypes.c_void_p()
    try:
        hr = _vtbl(uia, 8, ctypes.POINTER(ctypes.c_void_p))(uia, ctypes.byref(el))
    except Exception:  # noqa: BLE001
        return 0
    if not _ok(hr) or not el.value:
        return 0
    return int(el.value)


def _from_handle(uia: int, hwnd: int) -> int:
    el = ctypes.c_void_p()
    try:
        hr = _vtbl(uia, 6, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
            uia, hwnd, ctypes.byref(el)
        )
    except Exception:  # noqa: BLE001
        return 0
    if not _ok(hr) or not el.value:
        return 0
    return int(el.value)


def _from_point(uia: int, pt: POINT) -> int:
    el = ctypes.c_void_p()
    try:
        hr = _vtbl(uia, 7, POINT, ctypes.POINTER(ctypes.c_void_p))(
            uia, pt, ctypes.byref(el)
        )
    except Exception:  # noqa: BLE001
        return 0
    if not _ok(hr) or not el.value:
        return 0
    return int(el.value)


def _parent(uia: int, el: int) -> int:
    walker = _control_walker(uia)
    if not walker:
        return 0
    parent = ctypes.c_void_p()
    try:
        hr = _vtbl(
            walker, 3, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
        )(walker, el, ctypes.byref(parent))
    except Exception:  # noqa: BLE001
        return 0
    if not _ok(hr) or not parent.value:
        return 0
    return int(parent.value)


def _control_walker(uia: int) -> int:
    cached = int(getattr(_tls, "walker", 0) or 0)
    if cached:
        return cached
    walker = ctypes.c_void_p()
    try:
        hr = _vtbl(uia, 14, ctypes.POINTER(ctypes.c_void_p))(uia, ctypes.byref(walker))
    except Exception:  # noqa: BLE001
        return 0
    if not _ok(hr) or not walker.value:
        return 0
    _tls.walker = int(walker.value)
    return int(walker.value)


def _selection_from_element(el: int) -> str:
    pattern = _text_pattern(el)
    if not pattern:
        return ""
    try:
        return _selection_from_pattern(pattern)
    finally:
        _release(pattern)


def _text_pattern(el: int) -> int:
    punk = ctypes.c_void_p()
    try:
        hr = _vtbl(
            el,
            14,
            ctypes.c_int,
            ctypes.POINTER(GUID),
            ctypes.POINTER(ctypes.c_void_p),
        )(el, UIA_TextPatternId, ctypes.byref(_IID_TEXT), ctypes.byref(punk))
    except Exception:  # noqa: BLE001
        hr = -1
    if _ok(hr) and punk.value:
        return int(punk.value)
    unk = ctypes.c_void_p()
    try:
        hr = _vtbl(
            el, 16, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)
        )(el, UIA_TextPatternId, ctypes.byref(unk))
    except Exception:  # noqa: BLE001
        return 0
    if not _ok(hr) or not unk.value:
        return 0
    typed = ctypes.c_void_p()
    try:
        hr = _vtbl(
            int(unk.value),
            0,
            ctypes.POINTER(GUID),
            ctypes.POINTER(ctypes.c_void_p),
        )(int(unk.value), ctypes.byref(_IID_TEXT), ctypes.byref(typed))
    finally:
        _release(int(unk.value))
    if not _ok(hr) or not typed.value:
        return 0
    return int(typed.value)


def _selection_from_pattern(pattern: int) -> str:
    """IUIAutomationTextPattern.GetSelection → IUIAutomationTextRangeArray."""
    arr = ctypes.c_void_p()
    try:
        hr = _vtbl(pattern, 5, ctypes.POINTER(ctypes.c_void_p))(
            pattern, ctypes.byref(arr)
        )
    except Exception:  # noqa: BLE001
        return ""
    if not _ok(hr) or not arr.value:
        return ""
    array = int(arr.value)
    try:
        length = ctypes.c_int(0)
        hr = _vtbl(array, 3, ctypes.POINTER(ctypes.c_int))(array, ctypes.byref(length))
        if not _ok(hr) or int(length.value) <= 0:
            return ""
        parts: list[str] = []
        for i in range(min(int(length.value), 4)):
            rng = ctypes.c_void_p()
            hr = _vtbl(
                array, 4, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)
            )(array, i, ctypes.byref(rng))
            if not _ok(hr) or not rng.value:
                continue
            try:
                chunk = _range_text(int(rng.value))
                if chunk:
                    parts.append(chunk)
            finally:
                _release(int(rng.value))
        return "\n".join(parts)
    finally:
        _release(array)


def _range_text(rng: int) -> str:
    bstr = ctypes.c_void_p()
    try:
        hr = _vtbl(rng, 12, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(
            rng, MAX_CHARS, ctypes.byref(bstr)
        )
    except Exception:  # noqa: BLE001
        return ""
    if not _ok(hr) or not bstr.value:
        return ""
    try:
        return ctypes.wstring_at(bstr.value) or ""
    finally:
        try:
            _SysFreeString(bstr)
        except Exception:  # noqa: BLE001
            pass