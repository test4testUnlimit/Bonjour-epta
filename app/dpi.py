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
    """Pin a Win32 window above others.

    Tk's ``winfo_id()`` is often an *inner* child HWND. SetWindowPos on that
    child does not lift the overrideredirect toplevel — the chip maps in logs
    but stays under Firefox (field: chip show + user sees nothing).
    Resolve GetAncestor(GA_ROOT) / GetParent first.
    """
    if sys.platform != "win32" or not hwnd:
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        GA_ROOT = 2
        root = int(user32.GetAncestor(int(hwnd), GA_ROOT) or 0)
        parent = int(user32.GetParent(int(hwnd)) or 0)
        target = root or parent or int(hwnd)

        HWND_TOPMOST = -1
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040
        SWP_NOACTIVATE = 0x0010
        user32.SetWindowPos(
            int(target),
            HWND_TOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW | SWP_NOACTIVATE,
        )
    except Exception:
        pass
