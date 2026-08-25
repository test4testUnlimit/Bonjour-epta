"""Tests for automatic field-bug signatures."""

from __future__ import annotations

from unittest.mock import patch

from app import auto_catch


class TestLooksStrayC:
    def test_lone_c(self):
        assert auto_catch.looks_stray_c("c") == "lone_c"
        assert auto_catch.looks_stray_c("с") == "lone_c"

    def test_prefix(self):
        assert auto_catch.looks_stray_c("cInturristo") is not None
        assert auto_catch.looks_stray_c("Inturristo") is None

    def test_normal(self):
        assert auto_catch.looks_stray_c("Russo Inturristo") is None
        assert auto_catch.looks_stray_c("") is None


class TestEmitThrottle:
    def test_empty_calls_report(self):
        with (
            patch("app.auto_catch.bug_report.report") as rep,
            patch("app.auto_catch.peers.summary", return_value="ShareX"),
            patch.dict(auto_catch._last_by_kind, {}, clear=True),
            patch.object(auto_catch, "_hour_count", 0),
        ):
            auto_catch.note_empty_capture(polls=12, previous_head="ShareX\\Screenshots")
            # report runs on a daemon thread — wait briefly
            import time

            for _ in range(50):
                if rep.called:
                    break
                time.sleep(0.02)
            rep.assert_called_once()
            assert rep.call_args.args[0] == auto_catch.KIND_AUTO_EMPTY
            assert rep.call_args.kwargs.get("auto") is True
