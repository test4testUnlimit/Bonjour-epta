"""Ctrl+C goes in as ONE SendInput call.

MSDN guarantees only that the events of a *single* call are not interleaved
with another thread's input. The old code made three calls and separated
them with a GetAsyncKeyState poll — which reads the global async key table
and says nothing about what the target's message queue will see. A C that
arrived without its Ctrl typed a bare letter over the user's selection.
"""

import ctypes
from unittest.mock import patch

import pytest

from app.selection import _send_ctrl_c_win

VK_CONTROL = 0x11
VK_C = 0x43
KEYEVENTF_KEYUP = 0x0002


class FakeUser32:
    """Records each SendInput call as a list of (vk, flags)."""

    def __init__(self, accept=None):
        self.calls: list[list[tuple[int, int]]] = []
        self._accept = accept  # None = accept everything

    def SendInput(self, n, arr, size):
        buf = ctypes.cast(arr, ctypes.POINTER(ctypes.c_byte * (size * n))).contents
        events = []
        for i in range(n):
            # type (DWORD) then KEYBDINPUT: wVk, wScan (WORD), dwFlags (DWORD)
            base = i * size
            raw = bytes(buf[base : base + size])
            vk = int.from_bytes(raw[8:10], "little")
            flags = int.from_bytes(raw[12:16], "little")
            events.append((vk, flags))
        self.calls.append(events)
        return n if self._accept is None else self._accept

    def MapVirtualKeyW(self, vk, _mode):
        return vk

    def GetForegroundWindow(self):
        return 0

    def __getattr__(self, _name):
        return lambda *a, **k: 0


@pytest.fixture
def injected():
    """Force the SendInput path: WM_COPY must miss, arbiter must be free."""
    fake = FakeUser32()

    def run(accept=None):
        fake._accept = accept
        with (
            patch("app.selection.input_arbiter.busy", return_value=False),
            patch("app.selection._clipboard_seq", return_value=0),
            # both walk the process/window list with a mocked windll and
            # would spin forever on a truthy MagicMock
            patch("app.peers.log_snapshot"),
            patch("app.diag.foreground", return_value=None),
            patch("ctypes.windll") as windll,
        ):
            windll.user32 = fake
            windll.kernel32.GetCurrentThreadId.return_value = 1
            return _send_ctrl_c_win(), fake.calls

    return run


def test_ctrl_c_is_one_atomic_sendinput(injected):
    res, calls = injected()
    assert res is True
    assert len(calls) == 1, "three calls let another thread slip between them"
    assert [vk for vk, _ in calls[0]] == [VK_CONTROL, VK_C, VK_C, VK_CONTROL]
    assert [f for _, f in calls[0]] == [0, 0, KEYEVENTF_KEYUP, KEYEVENTF_KEYUP]


def test_nothing_injected_is_reported_as_retryable(injected):
    res, _ = injected(accept=0)
    assert res is False  # caller may try keyboard.send


def test_partial_injection_releases_ctrl_and_blocks_retry(injected):
    res, calls = injected(accept=2)
    assert res is None  # never retry — a second C would land bare
    assert calls[-1] == [(VK_CONTROL, KEYEVENTF_KEYUP)]
