"""The STA worker asks again while the provider wakes up.

A cold Chromium accessibility tree answers empty and *fast* — the first
GetSelection only flips AXMode on and IPCs the renderer. One extra look
50 ms later used to be the whole retry budget; submit() waits 1.4 s, so
there is room to keep asking.
"""

import threading
import time as real_time
from unittest.mock import patch

import pytest

from app import silent_selection as ss


class Clock:
    """Virtual time: sleep() advances it instead of costing wall-clock, so
    the 1.1 s retry budget is exercised in microseconds."""

    def __init__(self):
        self.t = 0.0

    def perf_counter(self):
        return self.t

    def sleep(self, d):
        self.t += d


@pytest.fixture
def worker():
    """A private worker (the module-level one owns a real thread) driven on a
    virtual clock, with COM and the message pump stubbed out."""
    clock = Clock()
    w = ss._StaWorker()
    with (
        patch.object(ss, "time", clock),
        patch.object(ss, "_ensure_com", return_value=True),
        patch.object(ss, "_pump"),
    ):
        yield w, clock


def test_retries_until_provider_wakes(worker):
    w, _clock = worker
    calls = {"n": 0}

    def read(_hwnd):
        calls["n"] += 1
        return "woke" if calls["n"] >= 3 else ""

    with patch.object(ss, "_read_uia", side_effect=read):
        assert w.submit(None) == "woke"
    assert calls["n"] == 3


def test_gives_up_inside_the_submit_budget(worker):
    """Never spin past submit()'s timeout — a retry loop that outlives its
    waiter strands every later gesture behind the worker."""
    w, clock = worker
    with patch.object(ss, "_read_uia", return_value="") as read:
        assert w.submit(None) == ""
    assert read.call_count > 1
    assert clock.t < ss._UIA_TIMEOUT_S


def test_warm_is_single_shot(worker):
    """A warm probe has no waiter. If it ran the retry loop it would hold the
    worker while the real read queued up behind it."""
    w, _clock = worker
    seen: list[int] = []
    done = threading.Event()

    def read(_hwnd):
        seen.append(1)
        done.set()
        return ""

    with patch.object(ss, "_read_uia", side_effect=read):
        w.warm()
        assert done.wait(2.0)
        real_time.sleep(0.05)  # a retry loop would burn through here
        assert len(seen) == 1
