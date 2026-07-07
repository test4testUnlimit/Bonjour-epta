"""Frameless window helpers (custom title bar, taskbar icon on Windows)."""

from __future__ import annotations

import sys
from typing import Any


def hwnd_of(widget: Any) -> int:
    """Top-level HWND for a Tk/CTk root."""
    if sys.platform != "win32":
        return 0
    try:
        import ctypes

        widget.update_idletasks()
        wid = int(widget.winfo_id())
        # CTk/Tk: parent of the inner frame is the real toplevel HWND
        parent = ctypes.windll.user32.GetParent(wid)
        return int(parent or wid)
    except Exception:
        return 0


def make_appwindow(widget: Any) -> None:
    """
    After overrideredirect(True), ensure the window still appears on the taskbar
    and is a normal app window (not a tool window).
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = hwnd_of(widget)
        if not hwnd:
            return
        GWL_EXSTYLE = -20
        WS_EX_APPWINDOW = 0x00040000
        WS_EX_TOOLWINDOW = 0x00000080
        get_long = ctypes.windll.user32.GetWindowLongW
        set_long = ctypes.windll.user32.SetWindowLongW
        style = get_long(hwnd, GWL_EXSTYLE)
        style = (style | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
        set_long(hwnd, GWL_EXSTYLE, style)
        # re-show to refresh taskbar
        SW_HIDE, SW_SHOW = 0, 5
        ctypes.windll.user32.ShowWindow(hwnd, SW_HIDE)
        ctypes.windll.user32.ShowWindow(hwnd, SW_SHOW)
    except Exception:
        pass


def work_area() -> tuple[int, int, int, int]:
    """Monitor work area (x, y, w, h) excluding taskbar — primary if multi fails."""
    if sys.platform != "win32":
        return 0, 0, 1280, 800
    try:
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = (
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            )

        rect = RECT()
        # SPI_GETWORKAREA = 0x0030
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)
        return (
            int(rect.left),
            int(rect.top),
            int(rect.right - rect.left),
            int(rect.bottom - rect.top),
        )
    except Exception:
        return 0, 0, 1280, 800
