"""Window / taskbar icon from project root app.ico (preferred) or app.png."""

from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path

_ICON_NAMES = ("app.ico", "app.png")


def _search_roots() -> list[Path]:
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    else:
        roots.append(Path(__file__).resolve().parent.parent)
    return roots


def find_icon() -> Path | None:
    for root in _search_roots():
        for name in _ICON_NAMES:
            path = root / name
            if path.is_file():
                return path
    return None


def _cache_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "bonjur-epta"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _ico_for(path: Path) -> Path:
    if path.suffix.lower() == ".ico":
        return path
    cache = _cache_dir() / "icon.ico"
    try:
        src_mtime = path.stat().st_mtime
        if cache.is_file() and cache.stat().st_mtime >= src_mtime:
            return cache
    except OSError:
        pass
    try:
        from PIL import Image

        img = Image.open(path).convert("RGBA")
        sizes = (16, 24, 32, 48, 64, 128, 256)
        icons = [img.resize((s, s), Image.Resampling.LANCZOS) for s in sizes]
        icons[0].save(
            cache,
            format="ICO",
            sizes=[(i.width, i.height) for i in icons],
            append_images=icons[1:],
        )
        return cache
    except Exception:  # noqa: BLE001
        return path


def _load_hicon(ico: Path) -> int:
    import ctypes

    LR_LOADFROMFILE = 0x00000010
    IMAGE_ICON = 1
    h = ctypes.windll.user32.LoadImageW(0, str(ico), IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
    return int(h or 0)


def apply_hwnd(hwnd: int, path: Path | None = None, *, attempts: int = 3) -> bool:
    if sys.platform != "win32" or not hwnd:
        return False
    src = path or find_icon()
    if src is None:
        return False
    try:
        import ctypes

        ico = _ico_for(src)
        WM_SETICON = 0x0080
        ok = False
        for _ in range(max(1, attempts)):
            hicon = _load_hicon(ico)
            if not hicon:
                return False
            # ICON_SMALL (0) + ICON_BIG (1)
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, 0, hicon)
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, 1, hicon)
            ok = True
            ctypes.windll.user32.InvalidateRect(hwnd, None, True)
        return ok
    except Exception:  # noqa: BLE001
        return False


def apply(toplevel: tk.Misc) -> Path | None:
    path = find_icon()
    if path is None:
        return None
    try:
        if path.suffix.lower() == ".ico":
            toplevel.iconbitmap(str(path))
        else:
            img = tk.PhotoImage(file=str(path))
            toplevel.iconphoto(True, img)
            setattr(toplevel, "_bonjur_icon_ref", img)
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import winframe

        hwnd = winframe.hwnd_of(toplevel)
        # retry a few times: make_appwindow hide/show can reset the icon
        def _retry(n: int = 4) -> None:
            if apply_hwnd(hwnd, path):
                return
            if n > 1:
                try:
                    toplevel.after(250, lambda: _retry(n - 1))
                except Exception:  # noqa: BLE001
                    pass

        _retry()
    except Exception:  # noqa: BLE001
        pass
    return path
