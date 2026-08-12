"""Repro #2 — LATE image write (timing race).

Scenario the early-exit cannot catch: the clipboard holds TEXT when bonjur
starts grabbing, and the screenshot tool drops an IMAGE mid-capture (after our
pre-clear / Ctrl+C). The second line of defence — the non_text_present() check
inside _restore_verdict — must stop us restoring stale text over that image.

We simulate the late write by monkeypatching selection._send_ctrl_c so that at
the exact moment bonjur "injects", an image is placed on the clipboard instead
of any selection text.

Run:  python tools\\repro_sharex_late.py   (no third-party deps)
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
    pixels = bytes((40, 160, 60)) * w
    pad = b"\x00" * (row - w * 3)
    body = b"".join((pixels + pad) for _ in range(h))
    header = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(body), 2835, 2835, 0, 0)
    return header + body


def _put_image() -> bool:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE

    dib = _make_dib()
    if not user32.OpenClipboard(0):
        return False
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(dib))
        if not h:
            return False
        ptr = kernel32.GlobalLock(h)
        ctypes.memmove(ptr, dib, len(dib))
        kernel32.GlobalUnlock(h)
        return bool(user32.SetClipboardData(CF_DIB, h))
    finally:
        user32.CloseClipboard()


def main() -> int:
    if sys.platform != "win32":
        print("SKIP: Windows only")
        return 0

    import pyperclip

    from app import selection

    # Start with TEXT on the clipboard (so early-exit does NOT fire).
    pyperclip.copy("STALE TEXT that must NOT be restored over the screenshot")
    print("before: has_text=%s formats=%s" % (clip_formats.has_text(), clip_formats.describe()))

    # Monkeypatch the inject to drop an image mid-capture (the timing race).
    def fake_send_ctrl_c() -> bool:
        _put_image()
        print("  (injected image mid-capture, formats=%s)" % clip_formats.describe())
        return True

    selection._send_ctrl_c = fake_send_ctrl_c  # type: ignore[assignment]

    out = selection.get_selected_text(restore_clipboard=True, settle_s=0.3)
    print("get_selected_text returned len=%s" % len(out or ""))

    still = clip_formats.has_image()
    print("after: has_image=%s formats=%s" % (still, clip_formats.describe()))

    if still:
        print("PASS: late image survived — _restore_verdict guard held")
        return 0
    print("FAIL: stale text restored over the late image")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())