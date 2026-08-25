"""Regression for the ShareX clipboard behaviour (owner rule).

Owner rule: selecting TEXT -> chip (text captured); a SCREENSHOT/image with no
text selected -> the image stays ready to paste.

Scenario A (screenshot, no text): image on clipboard, capture finds no text
  -> image must survive (restored).
Scenario B (text selected while image on clipboard): a fake Ctrl+C puts TEXT
  on the clipboard -> get_selected_text returns that text (chip will show).

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
    header = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(body), 2835, 2835, 0, 0)
    return header + body


def _put_image() -> bool:
    return clip_formats.set_image_dib(_make_dib())


def scenario_a() -> bool:
    """Screenshot, no text selected -> image survives."""
    from app import selection

    if not _put_image():
        print("A SKIP: cannot set image")
        return True
    assert clip_formats.has_image(), "A setup failed"
    out = selection.get_selected_text(restore_clipboard=True, settle_s=0.3)
    still = clip_formats.has_image()
    print("A: returned len=%s has_image_after=%s formats=%s" % (len(out or ""), still, clip_formats.describe()))
    ok = still and not out
    print("A:", "PASS image survived" if ok else "FAIL image lost")
    return ok


def scenario_b() -> bool:
    """Text selected while image on clipboard -> chip text captured."""
    from app import selection

    if not _put_image():
        print("B SKIP: cannot set image")
        return True

    import pyperclip

    def fake_send_ctrl_c() -> bool:
        pyperclip.copy("hello world selected text")
        return True

    orig = selection._send_ctrl_c
    selection._send_ctrl_c = fake_send_ctrl_c  # type: ignore[assignment]
    try:
        out = selection.get_selected_text(restore_clipboard=True, settle_s=0.3)
    finally:
        selection._send_ctrl_c = orig  # type: ignore[assignment]
    print("B: returned len=%s text=%r" % (len(out or ""), (out or "")[:40]))
    ok = out.strip() == "hello world selected text"
    print("B:", "PASS chip text captured" if ok else "FAIL no text for chip")
    return ok


def main() -> int:
    if sys.platform != "win32":
        print("SKIP: Windows only")
        return 0
    a = scenario_a()
    b = scenario_b()
    if a and b:
        print("ALL PASS: text->chip, image->preserved")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())