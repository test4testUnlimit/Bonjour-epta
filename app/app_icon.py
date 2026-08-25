"""Unified window / taskbar / tray icon from app.png (multi-size .ico).

Windows shows the pythonw.exe icon on the taskbar unless we:
1) set a unique AppUserModelID before any HWND exists, and
2) send proper ICON_SMALL (16) + ICON_BIG (32) via WM_SETICON.
"""

from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path

_ICON_NAMES = ("app.png", "app.ico")  # prefer PNG as source of truth
_AUMID = "BonjurEpta.Translator.1.6"
_AUMID_SET = False
_KEEP_HICONS: list[int] = []  # prevent GC / early DestroyIcon


def _search_roots() -> list[Path]:
    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    else:
        roots.append(Path(__file__).resolve().parent.parent)
    # installed next to main.py
    try:
        roots.append(Path(sys.argv[0]).resolve().parent)
    except Exception:  # noqa: BLE001
        pass
    # de-dupe preserve order
    out: list[Path] = []
    seen: set[str] = set()
    for r in roots:
        key = str(r).lower()
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def find_icon() -> Path | None:
    """Best source asset (PNG preferred)."""
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


def set_app_user_model_id(aumid: str = _AUMID) -> bool:
    """Must run before any window is created — otherwise taskbar keeps pythonw icon."""
    global _AUMID_SET
    if sys.platform != "win32" or _AUMID_SET:
        return _AUMID_SET
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(str(aumid))
        _AUMID_SET = True
        return True
    except Exception:  # noqa: BLE001
        return False


def _build_multi_ico(src: Path, dest: Path) -> Path | None:
    try:
        from PIL import Image

        img = Image.open(src).convert("RGBA")
        sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Pillow 10+: pass full image + sizes=… (append_images of 16px base yields tiny ICO)
        img.save(dest, format="ICO", sizes=sizes)
        return dest if dest.is_file() and dest.stat().st_size > 1024 else None
    except Exception:  # noqa: BLE001
        return None


def resolve_multi_ico() -> Path | None:
    """Always return a multi-size .ico in LOCALAPPDATA (writable even under Program Files)."""
    src = find_icon()
    if src is None:
        return None
    cache = _cache_dir() / "app_multi.ico"
    try:
        src_mtime = src.stat().st_mtime
        if (
            cache.is_file()
            and cache.stat().st_size > 1024
            and cache.stat().st_mtime >= src_mtime
        ):
            return cache
    except OSError:
        pass
    built = _build_multi_ico(src, cache)
    if built is not None:
        return built
    if src.suffix.lower() == ".ico" and src.is_file():
        return src
    return None


def load_tray_image():
    """PIL image for pystray — same artwork as window/taskbar."""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001
        return None
    src = find_icon()
    if src is None:
        return None
    try:
        img = Image.open(src).convert("RGBA")
        return img.resize((64, 64), Image.Resampling.LANCZOS)
    except Exception:  # noqa: BLE001
        return None


def _load_hicon_sized(ico: Path, cx: int, cy: int) -> int:
    import ctypes

    LR_LOADFROMFILE = 0x00000010
    IMAGE_ICON = 1
    h = ctypes.windll.user32.LoadImageW(
        0, str(ico), IMAGE_ICON, int(cx), int(cy), LR_LOADFROMFILE
    )
    return int(h or 0)


def apply_hwnd(hwnd: int, path: Path | None = None, *, attempts: int = 3) -> bool:
    if sys.platform != "win32" or not hwnd:
        return False
    ico = resolve_multi_ico()
    if ico is None and path is not None:
        ico = _build_multi_ico(path, _cache_dir() / "app_multi.ico")
    if ico is None:
        return False
    try:
        import ctypes

        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        ok = False
        for _ in range(max(1, attempts)):
            h_small = _load_hicon_sized(ico, 16, 16)
            h_big = _load_hicon_sized(ico, 32, 32)
            if not h_small and not h_big:
                return False
            if h_small:
                _KEEP_HICONS.append(h_small)
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_small)
            if h_big:
                _KEEP_HICONS.append(h_big)
                ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_big)
            ok = True
            ctypes.windll.user32.InvalidateRect(hwnd, None, True)
        return ok
    except Exception:  # noqa: BLE001
        return False


def apply(toplevel: tk.Misc) -> Path | None:
    set_app_user_model_id()
    src = find_icon()
    ico = resolve_multi_ico()
    if ico is None and src is None:
        return None
    try:
        if ico is not None:
            toplevel.iconbitmap(default=str(ico))
            try:
                toplevel.iconbitmap(str(ico))
            except Exception:  # noqa: BLE001
                pass
        elif src is not None and src.suffix.lower() == ".png":
            img = tk.PhotoImage(file=str(src))
            toplevel.iconphoto(True, img)
            setattr(toplevel, "_bonjur_icon_ref", img)
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import winframe

        hwnd = winframe.hwnd_of(toplevel)

        def _retry(n: int = 6) -> None:
            if apply_hwnd(hwnd, src):
                if n > 1:
                    try:
                        # re-apply after shell may reset on map
                        toplevel.after(400, lambda: apply_hwnd(hwnd, src))
                    except Exception:  # noqa: BLE001
                        pass
                return
            if n > 1:
                try:
                    toplevel.after(200, lambda: _retry(n - 1))
                except Exception:  # noqa: BLE001
                    pass

        _retry()
    except Exception:  # noqa: BLE001
        pass
    return ico or src
