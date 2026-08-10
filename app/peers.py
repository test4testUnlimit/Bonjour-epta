"""Known clipboard / keyboard interferers on the same machine.

ShareX can own the clipboard (history, OCR, auto-copy). Caramba Switcher
hooks the keyboard for layout switching. Both race with our Ctrl+C inject
and restore — field bugs #1 (stray «с») and #2 (no chip) often correlate.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from . import logutil

# exe stem (lowercase, no .exe) → short label for logs / bug reports
KNOWN: dict[str, str] = {
    "sharex": "ShareX",
    "carambaswitcher": "Caramba Switcher",
    "cswitcher": "Caramba Switcher",
    "caramba": "Caramba Switcher",
    "punto": "Punto Switcher",
    "puntoswitcher": "Punto Switcher",
    "ditto": "Ditto",
    "clipx": "ClipX",
    "clipboardfusion": "ClipboardFusion",
    "clipdiary": "Clipdiary",
    "copyq": "CopyQ",
    "greenshot": "Greenshot",
    "lightshot": "Lightshot",
    "powertoys": "PowerToys",
    "powertoys.launcher": "PowerToys",
    "ahk": "AutoHotkey",
    "autohotkey": "AutoHotkey",
    "autohotkey64": "AutoHotkey",
    "autohotkey32": "AutoHotkey",
    "autohotkeyux": "AutoHotkey",
}


@dataclass(frozen=True)
class Peer:
    label: str
    exe: str
    pid: int


def list_peers() -> list[Peer]:
    """Running processes that commonly fight us for clipboard/keyboard."""
    if sys.platform != "win32":
        return []
    found: list[Peer] = []
    seen: set[tuple[str, int]] = set()
    try:
        for name, pid in _iter_processes():
            stem = name.lower()
            if stem.endswith(".exe"):
                stem = stem[:-4]
            label = KNOWN.get(stem)
            if label is None:
                # fuzzy: ShareX_portable, CarambaSwitcher64, …
                for key, lab in KNOWN.items():
                    if key in stem:
                        label = lab
                        break
            if label is None:
                continue
            key = (label, pid)
            if key in seen:
                continue
            seen.add(key)
            found.append(Peer(label=label, exe=name, pid=pid))
    except Exception:  # noqa: BLE001
        logutil.exc("peers.list")
    found.sort(key=lambda p: (p.label, p.pid))
    return found


def summary(peers: list[Peer] | None = None) -> str:
    peers = list_peers() if peers is None else peers
    if not peers:
        return "none"
    parts = [f"{p.label}({p.exe}#{p.pid})" for p in peers]
    return ", ".join(parts)


def log_snapshot(tag: str = "peers") -> list[Peer]:
    peers = list_peers()
    logutil.get().info("%s: %s", tag, summary(peers))
    return peers


def _iter_processes() -> list[tuple[str, int]]:
    """(exe_name, pid) via Toolhelp — no extra deps."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = (
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        )

    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return []
    out: list[tuple[str, int]] = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            return []
        while True:
            out.append((entry.szExeFile, int(entry.th32ProcessID)))
            if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snap)
    return out
