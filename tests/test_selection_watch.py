# -*- coding: utf-8 -*-
"""Tests for app.selection_watch."""
from __future__ import annotations
import time
from unittest.mock import patch, MagicMock
import pytest
from app.selection_watch import SelectionWatcher, _dist, MAX_CHARS, DEDUP_MS


class TestDist:
    def test_zero(self):
        assert _dist((0, 0), (0, 0)) == 0.0

    def test_horiz(self):
        assert _dist((0, 0), (3, 0)) == 3.0

    def test_diag(self):
        assert abs(_dist((0, 0), (3, 4)) - 5.0) < 0.001


class TestWatcherInit:
    def test_defaults(self):
        w = SelectionWatcher(on_selection=MagicMock())
        assert w._enabled is True
        assert w._busy is False
        assert w._handlers == []


class TestStartStop:
    def test_start_no_mouse_raises(self):
        w = SelectionWatcher(on_selection=MagicMock())
        with patch("app.selection_watch.mouse", None):
            with pytest.raises(RuntimeError):
                w.start()

    def test_start_hooks(self):
        mm = MagicMock()
        mm.on_button.return_value = "h"
        w = SelectionWatcher(on_selection=MagicMock())
        with patch("app.selection_watch.mouse", mm):
            w.start()
        assert mm.on_button.call_count == 2
        assert len(w._handlers) == 2

    def test_start_idempotent(self):
        mm = MagicMock()
        mm.on_button.return_value = "h"
        w = SelectionWatcher(on_selection=MagicMock())
        with patch("app.selection_watch.mouse", mm):
            w.start()
            w.start()
        assert len(w._handlers) == 2

    def test_stop_unhooks(self):
        mm = MagicMock()
        mm.on_button.return_value = "h"
        w = SelectionWatcher(on_selection=MagicMock())
        with patch("app.selection_watch.mouse", mm):
            w.start()
            w.stop()
        mm.unhook.assert_called()
        assert w._handlers == []

    def test_stop_without_start(self):
        SelectionWatcher(on_selection=MagicMock()).stop()


class TestPauseResume:
    def test_pause(self):
        w = SelectionWatcher(on_selection=MagicMock())
        w.pause()
        assert w._enabled is False

    def test_resume(self):
        w = SelectionWatcher(on_selection=MagicMock())
        w.pause()
        w.resume()
        assert w._enabled is True


class TestCaptureAndFire:
    @patch("app.selection_watch.get_selected_text", return_value="hello world")
    def test_fires_on_text(self, mock_gst):
        cb = MagicMock()
        w = SelectionWatcher(on_selection=cb)
        w._enabled = True
        w._capture_and_fire(100, 200)
        mock_gst.assert_called_once()
        cb.assert_called_once_with("hello world", 100, 200)

    @patch("app.selection_watch.get_selected_text", return_value="")
    def test_empty_no_fire(self, mock_gst):
        cb = MagicMock()
        w = SelectionWatcher(on_selection=cb)
        w._capture_and_fire(100, 200)
        cb.assert_not_called()

    @patch("app.selection_watch.get_selected_text", return_value=None)
    def test_none_no_fire(self, mock_gst):
        cb = MagicMock()
        w = SelectionWatcher(on_selection=cb)
        w._capture_and_fire(100, 200)
        cb.assert_not_called()

    @patch("app.selection_watch.get_selected_text")
    def test_too_long_no_fire(self, mock_gst):
        mock_gst.return_value = "x" * (MAX_CHARS + 1)
        cb = MagicMock()
        w = SelectionWatcher(on_selection=cb)
        w._capture_and_fire(100, 200)
        cb.assert_not_called()

    @patch("app.selection_watch.get_selected_text", return_value="hello")
    def test_dedup_same_text(self, mock_gst):
        cb = MagicMock()
        w = SelectionWatcher(on_selection=cb)
        w._capture_and_fire(100, 200)
        assert cb.call_count == 1
        w._capture_and_fire(100, 200)
        assert cb.call_count == 1

    @patch("app.selection_watch.get_selected_text", return_value="hello")
    def test_dedup_expires(self, mock_gst):
        cb = MagicMock()
        w = SelectionWatcher(on_selection=cb)
        w._capture_and_fire(100, 200)
        assert cb.call_count == 1
        w._last_fire_ts = time.perf_counter() - (DEDUP_MS / 1000 + 0.1)
        w._capture_and_fire(100, 200)
        assert cb.call_count == 2

    @patch("app.selection_watch.get_selected_text", return_value="hello")
    def test_different_text_no_dedup(self, mock_gst):
        cb = MagicMock()
        w = SelectionWatcher(on_selection=cb)
        w._capture_and_fire(100, 200)
        mock_gst.return_value = "world"
        w._capture_and_fire(100, 200)
        assert cb.call_count == 2

    @patch("app.selection_watch.get_selected_text", return_value="text")
    def test_concurrent_capture_dropped(self, mock_gst):
        cb = MagicMock()
        w = SelectionWatcher(on_selection=cb)
        w._cap_lock.acquire()
        try:
            w._capture_and_fire(100, 200)
            cb.assert_not_called()
        finally:
            w._cap_lock.release()

    @patch("app.selection_watch.get_selected_text", side_effect=Exception("boom"))
    def test_exception_no_crash(self, mock_gst):
        cb = MagicMock()
        w = SelectionWatcher(on_selection=cb)
        w._capture_and_fire(100, 200)
        cb.assert_not_called()

    @patch("app.selection_watch.get_selected_text", return_value="text")
    def test_busy_flag_reset(self, mock_gst):
        cb = MagicMock()
        w = SelectionWatcher(on_selection=cb)
        w._capture_and_fire(100, 200)
        assert w._busy is False

    @patch("app.selection_watch.get_selected_text", return_value="text")
    def test_enabled_restored(self, mock_gst):
        cb = MagicMock()
        w = SelectionWatcher(on_selection=cb)
        w._enabled = True
        w._capture_and_fire(100, 200)
        assert w._enabled is True
