"""The two silent holes in the mouse state machine.

Both produce the same user-visible symptom — "selected something, no chip" — and
neither left a single line in the log, which is why they survived so long.
"""

from unittest.mock import patch

import pytest

from app.selection_watch import SelectionWatcher


class FakeMouse:
    """Just enough of the `mouse` package to drive the two handlers."""

    def __init__(self):
        self.pos = (0, 0)
        self.down = None
        self.up = None

    def on_button(self, fn, *, buttons, types):
        if types == ("down",):
            self.down = fn
        else:
            self.up = fn
        return object()

    def get_position(self):
        return self.pos

    def unhook(self, _h):
        pass


@pytest.fixture
def wired():
    """A started watcher plus the fake mouse and a list of fired captures."""
    fm = FakeMouse()
    fired: list[tuple[int, int]] = []
    # warm() is stubbed for every test here: a real probe spins up COM on the
    # module worker and its reply lands in whatever test is running by then.
    with patch("app.selection_watch.mouse", fm), patch(
        "app.selection_watch.input_arbiter.busy", return_value=False
    ), patch("app.silent_selection.warm"):
        w = SelectionWatcher(lambda *_: None)
        # A real capture thread would touch UIA and make this racy; record the
        # (x, y) the watcher wanted to capture at and start nothing.
        with patch("app.selection_watch.threading.Thread") as th:
            th.side_effect = lambda target, args, daemon: type(
                "T", (), {"start": lambda _s: fired.append(args[:2])}
            )()
            w.start()
            yield w, fm, fired


def drag(fm, frm, to):
    fm.pos = frm
    fm.down()
    fm.pos = to
    fm.up()


class TestPauseDoesNotEatTheNextDrag:
    """A hotkey pauses the watcher for 0.4-5.4 s. A drag that *starts* inside
    that window used to arrive at mouse-up with no down position, look like a
    bare click and vanish without a log line."""

    def test_drag_started_while_paused_still_fires(self, wired):
        w, fm, fired = wired
        w.pause()
        fm.pos = (100, 100)
        fm.down()  # down swallowed by the old code
        w.resume()
        fm.pos = (400, 100)
        fm.up()
        assert fired == [(400, 100)]

    def test_drag_entirely_inside_the_pause_still_fires_nothing(self, wired):
        w, fm, fired = wired
        w.pause()
        drag(fm, (100, 100), (400, 100))
        assert fired == []


class TestBusyDoesNotDesyncDoubleClick:
    """_busy used to bail before the up history was written, so the click that
    completed a double-click was measured against the previous word."""

    def test_double_click_after_a_swallowed_up(self, wired):
        w, fm, fired = wired
        w._last_up_ts = 0.0
        w._last_up_pos = (10, 10)  # previous gesture, far away

        w._busy = True
        fm.pos = (500, 300)
        fm.down()
        fm.up()  # swallowed — but must still record (500, 300)
        assert fired == []

        w._busy = False
        fm.down()
        fm.up()  # same spot, well inside DOUBLE_CLICK_MS
        assert fired == [(500, 300)]

    def test_a_swallowed_up_is_logged(self, wired, caplog):
        w, fm, _ = wired
        w._busy = True
        with caplog.at_level("INFO", logger="bonjur"):
            fm.pos = (5, 5)
            fm.down()
            fm.up()
        assert any("capture busy" in r.message for r in caplog.records)


class TestWarmOnDown:
    """Chromium's a11y tree is cold until someone asks. Ask at mouse-down so
    the read at mouse-up hits a tree that already exists."""

    def test_down_warms_provider(self, wired):
        _w, fm, _ = wired
        with patch("app.silent_selection.warm") as warm:
            fm.down()
        warm.assert_called_once_with()

    def test_down_does_not_warm_when_input_busy(self, wired):
        _w, fm, _ = wired
        with patch("app.selection_watch.input_arbiter.busy", return_value=True), patch(
            "app.silent_selection.warm"
        ) as warm:
            fm.down()
        warm.assert_not_called()
