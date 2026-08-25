"""Create a Win32 Edit, select a word, read it without Ctrl+C."""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import silent_selection  # noqa: E402
from app.selection import get_selected_text  # noqa: E402

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_EX_TOOLWINDOW = 0x00000080
WM_SETTEXT = 0x000C
EM_SETSEL = 0x00B1
SW_SHOW = 5
SW_HIDE = 0

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class WNDCLASSW(ctypes.Structure):
    _fields_ = (
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HANDLE),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    )


def _def_proc(hwnd, msg, wparam, lparam):
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


_wndproc = WNDPROC(_def_proc)

user32.DefWindowProcW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.SendMessageW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.SendMessageW.restype = LRESULT
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetFocus.argtypes = [wintypes.HWND]
user32.SetFocus.restype = wintypes.HWND
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.PeekMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
    wintypes.UINT,
]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]


def _pump(ms: int = 80) -> None:
    msg = wintypes.MSG()
    deadline = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < deadline:
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.01)


def main() -> int:
    cls_name = "BonjurSilentSelTest"
    hinst = kernel32.GetModuleHandleW(None)
    wc = WNDCLASSW()
    wc.lpfnWndProc = _wndproc
    wc.hInstance = hinst
    wc.lpszClassName = cls_name
    atom = user32.RegisterClassW(ctypes.byref(wc))
    if not atom and kernel32.GetLastError() not in (0, 1410):
        print("FAIL register class", kernel32.GetLastError())
        return 1

    hwnd = user32.CreateWindowExW(
        WS_EX_TOOLWINDOW,
        cls_name,
        "bonjur-silent-test",
        WS_OVERLAPPEDWINDOW,
        40,
        40,
        360,
        160,
        None,
        None,
        hinst,
        None,
    )
    if not hwnd:
        print("FAIL create frame", kernel32.GetLastError())
        return 1
    edit = user32.CreateWindowExW(
        0,
        "Edit",
        None,
        WS_CHILD | WS_VISIBLE | 0x0004 | 0x0080,
        8,
        8,
        330,
        110,
        hwnd,
        None,
        hinst,
        None,
    )
    if not edit:
        print("FAIL create edit", kernel32.GetLastError())
        user32.DestroyWindow(hwnd)
        return 1

    phrase = "Hello silent world"
    buf = ctypes.create_unicode_buffer(phrase)
    user32.SendMessageW(edit, WM_SETTEXT, 0, ctypes.addressof(buf))
    start = phrase.index("silent")
    user32.SendMessageW(edit, EM_SETSEL, start, start + len("silent"))
    user32.ShowWindow(hwnd, SW_SHOW)
    user32.SetForegroundWindow(hwnd)
    user32.SetFocus(edit)
    _pump(120)

    native = silent_selection.read_hwnd(int(edit))
    print("native hwnd:", repr(native))
    via_api = get_selected_text(allow_inject=False)
    print("get_selected_text(allow_inject=False):", repr(via_api))

    user32.ShowWindow(hwnd, SW_HIDE)
    user32.DestroyWindow(hwnd)

    if native == "silent":
        print("PASS native Edit selection without Ctrl+C")
        return 0
    print("FAIL expected 'silent', got", repr(native))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())