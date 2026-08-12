"""Ask Windows what *kind* of data is on the clipboard, without reading it.

pyperclip only sees CF_UNICODETEXT. When ShareX / Greenshot / Explorer put an
image (CF_DIB / CF_BITMAP) or files (CF_HDROP) on the clipboard, pyperclip reads
"" and our restore logic would happily write stale TEXT back over the image --
the user pastes yesterday's text instead of the screenshot.

This module lets selection.py step aside whenever the live clipboard holds a
non-text flavour. Read-only: EnumClipboardFormats never mutates the clipboard.
"""

from __future__ import annotations

import sys
import time

from . import logutil

CF_TEXT = 1
CF_BITMAP = 2
CF_DIB = 8
CF_UNICODETEXT = 13
CF_HDROP = 15
CF_DIBV5 = 17

_TEXT_FORMATS = frozenset((CF_TEXT, CF_UNICODETEXT))
_IMAGE_FORMATS = frozenset((CF_BITMAP, CF_DIB, CF_DIBV5))
_FILE_FORMATS = frozenset((CF_HDROP,))


def list_formats() -> list[int]:
    """Format ids currently on the clipboard. [] on non-win or on failure."""
    if sys.platform != "win32":
        return []
    import ctypes

    user32 = ctypes.windll.user32
    fmts: list[int] = []
    opened = False
    for _ in range(6):
        if user32.OpenClipboard(0):
            opened = True
            break
        time.sleep(0.01)
    if not opened:
        logutil.get().debug("clip_formats: OpenClipboard busy")
        return []
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