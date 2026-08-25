"""RichEdit hands back two different offset domains.

EM_GETSEL counts a line break as one character (RichEdit stores CR), but
WM_GETTEXT returns CRLF. Slicing the CRLF text with CR offsets shifts the
result left by one per preceding break, so selecting a word on line 3 used
to yield '\\r\\nWOR' instead of 'WORLD'.
"""

import ctypes
import sys
from ctypes import wintypes
from unittest.mock import patch

import pytest

from app import silent_selection as ss

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Win32 controls")

WS_CHILD = 0x40000000
ES_MULTILINE = 0x0004
HWND_MESSAGE = -3
EM_SETSEL = 0x00B1
WM_SETTEXT = 0x000C
DOC = "line one\r\nline two\r\nWORLD tail"


@pytest.fixture(scope="module")
def controls():
    """One real RICHEDIT50W and one plain EDIT holding the same document."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    if not ctypes.WinDLL("kernel32").LoadLibraryW("Msftedit.dll"):
        pytest.skip("Msftedit.dll unavailable")
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    made = {}
    for key, cls in (("rich", "RICHEDIT50W"), ("edit", "EDIT")):
        hwnd = user32.CreateWindowExW(
            0, cls, None, WS_CHILD | ES_MULTILINE, 0, 0, 200, 200,
            wintypes.HWND(HWND_MESSAGE), None, None, None,
        )
        if not hwnd:
            pytest.skip(f"cannot create {cls}: {ctypes.get_last_error()}")
        ss._send(int(hwnd), WM_SETTEXT, 0, ctypes.cast(
            ctypes.create_unicode_buffer(DOC), ctypes.c_void_p).value)
        made[key] = int(hwnd)
    yield made
    for hwnd in made.values():
        user32.DestroyWindow(wintypes.HWND(hwnd))


def select(hwnd, start, end):
    ss._send(hwnd, EM_SETSEL, start, end)


# Offsets in the CR domain the control itself uses: two breaks before "WORLD".
LINE3 = len("line one\rline two\r")


class TestRichEditOffsets:
    def test_word_on_the_third_line(self, controls):
        select(controls["rich"], LINE3, LINE3 + 5)
        assert ss._read_edit(controls["rich"], "RICHEDIT50W") == "WORLD"

    def test_short_range_is_not_all_newline(self, controls):
        """The old bug degraded worst on short selections — two chars came
        back as '\\r\\n', which sanitize drops, so the chip never appeared."""
        select(controls["rich"], LINE3, LINE3 + 2)
        assert ss._read_edit(controls["rich"], "RICHEDIT50W") == "WO"

    def test_first_line_was_never_broken(self, controls):
        select(controls["rich"], 0, 4)
        assert ss._read_edit(controls["rich"], "RICHEDIT50W") == "line"

    def test_plain_edit_is_left_alone(self, controls):
        """A plain EDIT has one offset domain — CRLF. Translating it too
        would break the control that always worked."""
        hwnd = controls["edit"]
        a = len("line one\r\nline two\r\n")
        select(hwnd, a, a + 5)
        assert ss._read_edit(hwnd, "Edit") == "WORLD"


class TestSendTimeout:
    """A bare SendMessageW to a hung foreign UI thread never returns, and the
    watcher's _busy flag never clears — no chip for the rest of the process."""

    def test_returns_zero_when_target_hangs(self):
        with patch.object(ss, "_SendMessageTimeoutW", return_value=0):
            assert ss._send(1234, ss.WM_GETTEXTLENGTH) == 0

    def test_passes_the_result_through(self):
        def fake(*a):
            a[-1]._obj.value = 7  # byref() arg — the c_size_t out-param
            return 1

        with patch.object(ss, "_SendMessageTimeoutW", side_effect=fake):
            assert ss._send(1234, ss.WM_GETTEXTLENGTH) == 7
