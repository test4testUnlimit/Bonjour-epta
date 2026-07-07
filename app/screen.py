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


def clamp_popup(x: int, y: int, width: int = 120, height: int = 44) -> tuple[int, int]:
    """
    Place popup near (x,y) without forcing coords onto primary (x>=0,y>=0).
    Negative virtual-screen coords are valid for monitors left/above primary.
    """
    vx, vy, vw, vh = virtual_screen_bounds()
    # slight offset from cursor / selection end
    px = x + 12
    py = y + 16
    # keep fully visible inside virtual desktop
    max_x = vx + vw - width
    max_y = vy + vh - height
    if max_x < vx:
        max_x = vx
    if max_y < vy:
        max_y = vy
    px = min(max(px, vx), max_x)
    py = min(max(py, vy), max_y)
    return px, py
