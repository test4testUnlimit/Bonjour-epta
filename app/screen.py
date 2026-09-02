"""Virtual-screen geometry (multi-monitor safe)."""

from __future__ import annotations

import sys


def virtual_screen_bounds() -> tuple[int, int, int, int]:
    """Return (vx, vy, vw, vh) of the Windows virtual screen, or (0,0,w,h) fallback."""
    if sys.platform == "win32":
        try:
            import ctypes

            user32 = ctypes.windll.user32
            # SM_XVIRTUALSCREEN=76, SM_YVIRTUALSCREEN=77,
            # SM_CXVIRTUALSCREEN=78, SM_CYVIRTUALSCREEN=79
            vx = int(user32.GetSystemMetrics(76))
            vy = int(user32.GetSystemMetrics(77))
            vw = int(user32.GetSystemMetrics(78))
            vh = int(user32.GetSystemMetrics(79))
            if vw > 0 and vh > 0:
                return vx, vy, vw, vh
        except Exception:  # noqa: BLE001
            pass
    return 0, 0, 1920, 1080


def work_area() -> tuple[int, int, int, int]:
    """Primary monitor work area (x, y, w, h), excluding taskbar. Screen pixels."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            rect = RECT()
            # SPI_GETWORKAREA = 0x0030
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                w = int(rect.right - rect.left)
                h = int(rect.bottom - rect.top)
                if w > 0 and h > 0:
                    return int(rect.left), int(rect.top), w, h
        except Exception:  # noqa: BLE001
            pass
    _vx, _vy, vw, vh = virtual_screen_bounds()
    return 0, 0, vw, vh


def work_area_at(x: int, y: int) -> tuple[int, int, int, int]:
    """Work area of the monitor that contains (x, y). Falls back to primary."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", RECT),
                    ("rcWork", RECT),
                    ("dwFlags", wintypes.DWORD),
                ]

            user32 = ctypes.windll.user32
            # MONITOR_DEFAULTTONEAREST = 2
            hmon = user32.MonitorFromPoint(POINT(int(x), int(y)), 2)
            if hmon:
                mi = MONITORINFO()
                mi.cbSize = ctypes.sizeof(MONITORINFO)
                if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                    r = mi.rcWork
                    w = int(r.right - r.left)
                    h = int(r.bottom - r.top)
                    if w > 0 and h > 0:
                        return int(r.left), int(r.top), w, h
        except Exception:  # noqa: BLE001
            pass
    return work_area()


def center_on_screen(win, *, _attempt: int = 0) -> None:
    """Put a Toplevel dead centre of the monitor work area (taskbar-safe).

    Windows of this app are expected in the middle of the display, not wherever
    the window manager felt like putting them or offset over the parent.

    A not-yet-mapped window reports winfo_width()==1; centring on that puts the
    TOP-LEFT corner in the middle of the screen (the 3.3.2 laptop report). When
    the size is not real yet, re-arm briefly and try again instead of guessing.
    """
    try:
        win.update_idletasks()
        # winfo_* and work_area() are both in PHYSICAL pixels, and so is the
        # +x+y that geometry() takes on Windows — but a CTk window scaled by the
        # DPI factor reports a physical size while its geometry string is
        # logical. Use the real on-screen rectangle to stay exact either way.
        w = int(win.winfo_width())
        h = int(win.winfo_height())
        if (w <= 1 or h <= 1) and _attempt < 20:
            try:
                win.after(30, lambda: center_on_screen(win, _attempt=_attempt + 1))
            except Exception:  # noqa: BLE001
                pass
            return
        if w <= 1 or h <= 1:
            w = int(win.winfo_reqwidth())
            h = int(win.winfo_reqheight())
        wx, wy, aw, ah = work_area()
        x = wx + (aw - w) // 2
        y = wy + (ah - h) // 2
        x = max(wx, min(x, wx + aw - w))
        y = max(wy, min(y, wy + ah - h))
        win.geometry(f"+{x}+{y}")
        # One correction pass: after the move we can measure where the window
        # actually landed and fix any DPI-induced drift.
        win.update_idletasks()
        got_x = int(win.winfo_rootx())
        got_y = int(win.winfo_rooty())
        dx = x - got_x
        dy = y - got_y
        if dx or dy:
            win.geometry(f"+{x + dx}+{y + dy}")
    except Exception:  # noqa: BLE001
        pass


def clamp_popup(
    x: int,
    y: int,
    width: int = 120,
    height: int = 44,
    *,
    gap: int = 8,
    prefer_below: bool = True,
) -> tuple[int, int]:
    """
    Place popup near (x,y) fully inside the monitor work area (taskbar-safe).

    Prefers below-right of the anchor; if it would clip, flips above and/or left.
    Negative virtual-screen coords are valid for monitors left/above primary.
    """
    wx, wy, ww, wh = work_area_at(int(x), int(y))
    margin = 6
    left = wx + margin
    top = wy + margin
    right = wx + ww - margin
    bottom = wy + wh - margin
    avail_w = max(right - left, 1)
    avail_h = max(bottom - top, 1)

    # If popup is larger than work area, pin to top-left of work area
    # (caller should also cap size, but be defensive).
    w = min(int(width), avail_w)
    h = min(int(height), avail_h)

    # Horizontal: prefer just right of anchor; flip left if clipped
    px = int(x) + gap
    if px + w > right:
        px = int(x) - gap - w
    if px < left:
        px = left
    if px + w > right:
        px = max(left, right - w)

    # Vertical: prefer below; flip above if clipped
    if prefer_below:
        py = int(y) + gap + 8
        if py + h > bottom:
            py = int(y) - gap - h
    else:
        py = int(y) - gap - h
        if py < top:
            py = int(y) + gap + 8

    if py < top:
        py = top
    if py + h > bottom:
        py = max(top, bottom - h)

    return px, py


def max_popup_size_at(
    x: int, y: int, *, frac: float = 0.82
) -> tuple[int, int]:
    """Largest sensible popup (w, h) on the monitor under (x, y)."""
    _wx, _wy, ww, wh = work_area_at(int(x), int(y))
    margin = 16
    max_w = max(int(ww - margin), 200)
    max_h = max(int(wh * frac) - margin, 160)
    return max_w, max_h
