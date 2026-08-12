"""Repro / regression for the ShareX clipboard bug.

Bug: after ShareX copies an IMAGE to the clipboard, bonjur's selection grab
restored stale TEXT over it, so the user pasted old text instead of the image.

Puts a real bitmap (CF_DIB) on the clipboard via pure ctypes, then calls
selection.get_selected_text() exactly like the mouse watcher does, and checks
the clipboard STILL holds an image afterwards.

Run:  python tools\\repro_sharex_clip.py   (no third-party deps)
"""

from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import clip_formats

CF_DIB = 8
GMEM_MOVEABLE = 0x0002


def _make_dib(w: int = 32, h: int = 16) -> bytes:
    row = ((w * 3 + 3) // 4) * 4
    pixels = bytes((200, 40, 40)) * w
    pad = b"\x00" * (row - w * 3)
    body = b"".join((pixels + pad) for _ in range(h))
    header = struct.pack(
        "<IiiHHIIiiII",
        40, w, h, 1, 24, 0, len(body), 2835, 2835, 0, 0,
    )
    return header + body


def _put_image_on_clipboard(dib: bytes) -> bool:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    # argtypes/restypes so 64-bit handles/pointers are not truncated
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE

    if not user32.OpenClipboard(0):
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
    finally:
        user32.CloseClipboard()


def main() -> int:
    if sys.platform != "win32":
        print("SKIP: Windows only")
        return 0
    try:
        ok = _put_image_on_clipboard(_make_dib())
    except Exception as e:  # noqa: BLE001
        print("SKIP: cannot set image clipboard:", e)
        return 0
    if not ok:
        print("SKIP: SetClipboardData failed")
        return 0

    print("before: has_image=%s formats=%s" % (clip_formats.has_image(), clip_formats.describe()))
    if not clip_formats.has_image():
        print("SKIP: setup did not register an image")
        return 0

    from app import selection

    out = selection.get_selected_text(restore_clipboard=True, settle_s=0.3)
    print("get_selected_text returned len=%s" % len(out or ""))

    still = clip_formats.has_image()
    print("after: has_image=%s formats=%s" % (still, clip_formats.describe()))

    if still and not out:
        print("PASS: image survived, bonjur stayed hands-off")
        return 0
    print("FAIL: image was clobbered (text restored over screenshot)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())