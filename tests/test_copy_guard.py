"""copy_guard: tell a real user Ctrl+C apart from the one we inject."""

import time
from unittest.mock import patch

import pytest

from app import copy_guard


class Ev:
    def __init__(self, scan_code, event_type="down"):
        self.scan_code = scan_code
        self.event_type = event_type


@pytest.fixture(autouse=True)
def clean():
    copy_guard.forget()
    copy_guard._inject_until = 0.0
    yield
    copy_guard.forget()
    copy_guard._inject_until = 0.0


def _press(scan, ctrl=True):
    with patch.object(copy_guard, "_ctrl_down", return_value=ctrl):
        copy_guard._on_event(Ev(scan))


class TestDetect:
    def test_ctrl_c(self):
        _press(copy_guard.SC_C)
        assert copy_guard.recent(1.0) is True

    def test_ctrl_x(self):
        _press(copy_guard.SC_X)
        assert copy_guard.recent(1.0) is True

    def test_ctrl_insert(self):
        _press(copy_guard.SC_INSERT)
        assert copy_guard.recent(1.0) is True

    def test_c_without_ctrl(self):
        _press(copy_guard.SC_C, ctrl=False)
        assert copy_guard.recent(1.0) is False

    def test_other_key(self):
        _press(17)  # W
        assert copy_guard.recent(1.0) is False

    def test_key_up_ignored(self):
        with patch.object(copy_guard, "_ctrl_down", return_value=True):
            copy_guard._on_event(Ev(copy_guard.SC_C, "up"))
        assert copy_guard.recent(1.0) is False

    def test_layout_is_irrelevant(self):
        """Scan code only — a Cyrillic layout reports the same 46."""
        _press(46)
        assert copy_guard.recent(1.0) is True


class TestCtrlDown:
    def test_keyboard_says_yes(self):
        with patch.object(copy_guard.keyboard, "is_pressed", return_value=True):
            assert copy_guard._ctrl_down() is True

    def test_falls_back_to_win32(self):
        """`keyboard` only tracks real keys; ask Windows before giving up."""
        with patch.object(copy_guard.keyboard, "is_pressed", return_value=False):
            with patch("ctypes.windll.user32.GetAsyncKeyState", return_value=-32767):
                assert copy_guard._ctrl_down() is True
            with patch("ctypes.windll.user32.GetAsyncKeyState", return_value=0):
                assert copy_guard._ctrl_down() is False

    def test_survives_a_broken_keyboard_lib(self):
        with patch.object(copy_guard.keyboard, "is_pressed", side_effect=OSError):
            with patch("ctypes.windll.user32.GetAsyncKeyState", return_value=0):
                assert copy_guard._ctrl_down() is False


class TestInjection:
    def test_injected_scan_code_is_negative(self):
        """Observed on Windows: our SendInput arrives as scan_code -67.

        `keyboard` reports `scan_code or -vk`; we inject by virtual key with
        wScan=0, so the code comes back negated. A finger on the key always
        carries a real scan code. Sturdier than the `injecting()` window —
        it holds even after that window lapses.
        """
        _press(-67)
        assert copy_guard.recent(1.0) is False

    def test_injected_negated_scan_code(self):
        _press(-copy_guard.SC_C)
        assert copy_guard.recent(1.0) is False

    def test_our_own_copy_does_not_count(self):
        with copy_guard.injecting():
            _press(copy_guard.SC_C)
        assert copy_guard.recent(1.0) is False

    def test_tail_still_guards_after_the_call(self):
        with copy_guard.injecting(tail_s=0.5):
            pass
        _press(copy_guard.SC_C)  # late-delivered hook event
        assert copy_guard.recent(1.0) is False

    def test_user_copy_after_tail_counts(self):
        with copy_guard.injecting(tail_s=0.0):
            pass
        time.sleep(0.01)
        _press(copy_guard.SC_C)
        assert copy_guard.recent(1.0) is True

    def test_exception_still_closes_the_window(self):
        with pytest.raises(RuntimeError), copy_guard.injecting(tail_s=0.0):
            raise RuntimeError("boom")
        time.sleep(0.01)
        _press(copy_guard.SC_C)
        assert copy_guard.recent(1.0) is True


class TestWindow:
    def test_copied_since(self):
        t0 = time.perf_counter()
        _press(copy_guard.SC_C)
        assert copy_guard.copied_since(t0) is True
        assert copy_guard.copied_since(time.perf_counter()) is False

    def test_recent_expires(self):
        _press(copy_guard.SC_C)
        assert copy_guard.recent(0.0) is False

    def test_never_copied(self):
        assert copy_guard.recent(10.0) is False
        assert copy_guard.copied_since(0.0) is False
        assert copy_guard.last_copy_ts() == 0.0

    def test_forget(self):
        _press(copy_guard.SC_C)
        copy_guard.forget()
        assert copy_guard.recent(1.0) is False
