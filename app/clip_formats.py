"""Ask Windows what *kind* of data is on the clipboard, and save/restore images.

pyperclip only sees CF_UNICODETEXT. When ShareX / Greenshot / Explorer put an
image (CF_DIB / CF_BITMAP) or files (CF_HDROP) on the clipboard, pyperclip reads
"" and our restore logic would happily write stale TEXT back over the image --
the user pastes yesterday's text instead of the screenshot.

Product rule (owner): selecting TEXT -> chip; a fresh SCREENSHOT -> image stays
ready to paste. selection.py saves the image (CF_DIB) before injecting Ctrl+C
and puts it back when no text was captured, so text->chip and image->preserved.

All ctypes; no pywin32 dependency. Reads never mutate the clipboard.
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

from . import logutil

CF_TEXT = 1
CF_BITMAP = 2
CF_DIB = 8
CF_UNICODETEXT = 13
CF_HDROP = 15
CF_DIBV5 = 17

GMEM_MOVEABLE = 0x0002

_TEXT_FORMATS = frozenset((CF_TEXT, CF_UNICODETEXT))
_IMAGE_FORMATS = frozenset((CF_BITMAP, CF_DIB, CF_DIBV5))
_FILE_FORMATS = frozenset((CF_HDROP,))


def _open_clipboard() -> bool:
    user32 = ctypes.windll.user32
    for _ in range(6):
        if user32.OpenClipboard(0):
            return True
        time.sleep(0.01)
    return False


def list_formats() -> list[int]:
    """Format ids currently on the clipboard. [] on non-win or on failure."""
    if sys.platform != "win32":
        return []
    user32 = ctypes.windll.user32
    if not _open_clipboard():
        logutil.get().debug("clip_formats: OpenClipboard busy")
        return []
    fmts: list[int] = []
    try:
        fmt = 0
        while True:
            fmt = int(user32.EnumClipboardFormats(fmt))
            if fmt == 0:
                break
            fmts.append(fmt)
    except Exception:  # noqa: BLE001
        logutil.exc("clip_formats enum")
    finally:
        try:
            user32.CloseClipboard()
        except Exception:  # noqa: BLE001
            pass
    return fmts


def has_image() -> bool:
    return any(f in _IMAGE_FORMATS for f in list_formats())


def has_files() -> bool:
    return any(f in _FILE_FORMATS for f in list_formats())


def has_text() -> bool:
    return any(f in _TEXT_FORMATS for f in list_formats())


def non_text_present() -> bool:
    """True if the clipboard holds image/file data (with or without text)."""
    fmts = list_formats()
    if not fmts:
        return False
    return any(f in _IMAGE_FORMATS or f in _FILE_FORMATS for f in fmts)


def describe() -> str:
    """Short human label of current formats -- for logs / bug reports."""
    fmts = list_formats()
    if not fmts:
        return "empty"
    names = {
        CF_TEXT: "TEXT",
        CF_BITMAP: "BITMAP",
        CF_DIB: "DIB",
        CF_UNICODETEXT: "UNICODETEXT",
        CF_HDROP: "HDROP(files)",
        CF_DIBV5: "DIBV5",
    }
    return ",".join(names.get(f, "#%d" % f) for f in fmts)


def get_image_dib() -> bytes | None:
    """Snapshot the clipboard image as raw CF_DIB bytes (None if no image)."""
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalSize.restype = ctypes.c_size_t
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE

    if not _open_clipboard():
        return None
    try:
        if not user32.IsClipboardFormatAvailable(CF_DIB):
            return None
        h = user32.GetClipboardData(CF_DIB)
        if not h:
            return None
        size = int(kernel32.GlobalSize(h))
        if size <= 0:
            return None
        ptr = kernel32.GlobalLock(h)
        if not ptr:
            return None
        try:
            buf = (ctypes.c_char * size).from_address(ptr)
            data = bytes(buf)
        finally:
            kernel32.GlobalUnlock(h)
        return data
    except Exception:  # noqa: BLE001
        logutil.exc("get_image_dib")
        return None
    finally:
        try:
            user32.CloseClipboard()
        except Exception:  # noqa: BLE001
            pass


def set_image_dib(dib: bytes) -> bool:
    """Put raw CF_DIB bytes back on the clipboard (replaces contents)."""
    if sys.platform != "win32" or not dib:
        return False
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE

    if not _open_clipboard():
        return False
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(dib))
        if not h:
            return False
        ptr = kernel32.GlobalLock(h)
        if not ptr:
            return False
        ctypes.memmove(ptr, dib, len(dib))
        kernel32.GlobalUnlock(h)
        return bool(user32.SetClipboardData(CF_DIB, h))
    except Exception:  # noqa: BLE001
        logutil.exc("set_image_dib")
        return False
    finally:
        try:
            user32.CloseClipboard()
        except Exception:  # noqa: BLE001
            pass