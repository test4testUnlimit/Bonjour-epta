"""Windows DPI awareness — must run BEFORE any Tk window.

Keeps mouse coords and Tk geometry on the same scale (multi-monitor).
"""

from __future__ import annotations

import sys

_DONE = False


def enable() -> str:
    global _DONE
    if _DONE or sys.platform != "win32":
        return "skip"
    _DONE = True
    try:
        import ctypes

        # 2 = PROCESS_PER_MONITOR_DPI_AWARE (Win 8.1+)
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            return "per-monitor-v1"
        except Exception:
            pass
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            return "system-aware"
        except Exception:
            pass
    except Exception:
        pass
    return "failed"


def force_topmost(hwnd: int) -> None:
    if sys.platform != "win32" or not hwnd:
        return
    try:
        import ctypes

        HWND_TOPMOST = -1
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040
        ctypes.windll.user32.SetWindowPos(
            int(hwnd),
            HWND_TOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
        )
    except Exception:
        pass
