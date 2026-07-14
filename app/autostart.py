"""Windows autostart — HKCU Run key (no admin)."""

from __future__ import annotations

import sys
from pathlib import Path

REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_NAME = "BonjurEpta"
STARTUP_FLAG = "--startup"


def supported() -> bool:
    return sys.platform == "win32"


def launch_command() -> str:
    """Command written to the Run key — includes --startup for quiet login boot."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        return f'"{exe}" {STARTUP_FLAG}'

    exe = Path(sys.executable).resolve()
    if exe.name.lower() == "python.exe":
        pyw = exe.with_name("pythonw.exe")
        if pyw.is_file():
            exe = pyw
    main_py = Path(__file__).resolve().parents[1] / "main.py"
    return f'"{exe}" "{main_py}" {STARTUP_FLAG}'


def is_enabled() -> bool:
    if not supported():
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_PATH) as key:
            winreg.QueryValueEx(key, REG_NAME)
            return True
    except OSError:
        return False


def set_enabled(on: bool) -> tuple[bool, str | None]:
    """Apply or remove Run entry. Returns (ok, error_message)."""
    if not supported():
        return False, "только Windows"
    import winreg

    try:
        if on:
            cmd = launch_command()
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(key, REG_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, REG_PATH, 0, winreg.KEY_SET_VALUE
                ) as key:
                    winreg.DeleteValue(key, REG_NAME)
            except FileNotFoundError:
                pass
        return True, None
    except OSError as exc:
        return False, str(exc)


def sync(want: bool) -> tuple[bool, str | None]:
    """Ensure registry matches the settings flag."""
    have = is_enabled()
    if want == have:
        return True, None
    return set_enabled(want)
