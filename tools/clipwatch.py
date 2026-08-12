"""Print what is on the clipboard RIGHT NOW — formats + short preview.

Use to see exactly what ShareX leaves after alt+shift+s:
  1) run:  python tools\\clipwatch.py
  2) it prints formats every second; do a ShareX capture and watch the change.
Ctrl+C to stop.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import clip_formats


def snapshot() -> str:
    fmts = clip_formats.describe()
    preview = ""
    try:
        if clip_formats.has_text():
            import pyperclip

            t = (pyperclip.paste() or "")[:80]
            preview = " text=%r" % t
        elif clip_formats.has_image():
            dib = clip_formats.get_image_dib()
            preview = " image_dib_bytes=%s" % (len(dib) if dib else 0)
        elif clip_formats.has_files():
            preview = " <files>"
    except Exception as e:  # noqa: BLE001
        preview = " (preview err: %s)" % e
    return "formats=[%s]%s" % (fmts, preview)


def main() -> int:
    print("clipwatch: do a ShareX capture; watch the line change. Ctrl+C to stop.")
    last = None
    try:
        while True:
            cur = snapshot()
            if cur != last:
                print(time.strftime("%H:%M:%S"), cur)
                last = cur
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())