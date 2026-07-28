import time
from unittest.mock import patch, MagicMock
import pytest
from app.hotkey import TranslateHotkey, DoubleTapHotkey
from app.win_hotkeys import HotkeySpec

def _ev(scan, etype="down"):
    e = MagicMock(); e.event_type = etype; e.scan_code = scan; return e

def _wire(fire, spec):
    mk = MagicMock(); hbox = [None]
    def cap(fn, suppress=False): hbox[0] = fn; return "handle"
    mk.hook.side_effect = cap; mk.is_pressed.return_value = False
    return TranslateHotkey(on_fire=fire, spec=spec), mk, hbox

class TestInit:
    def test_defaults(self):
        h = TranslateHotkey(on_fire=MagicMock())
        assert h.spec == HotkeySpec() and h._hook is None
    def test_custom(self):
        assert TranslateHotkey(on_fire=MagicMock(), spec=HotkeySpec(scan_code=30)).spec.scan_code == 30
    def test_alias(self):
        assert DoubleTapHotkey is TranslateHotkey

class TestStartStop:
    def test_no_kb(self):
        with patch("app.hotkey.keyboard", None):
            with pytest.raises(RuntimeError): TranslateHotkey(on_fire=MagicMock()).start()
    def test_hooks(self):
        mk = MagicMock(); mk.hook.return_value = "h"
        h = TranslateHotkey(on_fire=MagicMock())
        with patch("app.hotkey.keyboard", mk): h.start()
        assert h._hook == "h"
    def test_unhooks(self):
        mk = MagicMock(); mk.hook.return_value = "h"
        h = TranslateHotkey(on_fire=MagicMock())
        with patch("app.hotkey.keyboard", mk): h.start(); h.stop()
        mk.unhook.assert_called_once_with("h")
    def test_stop_noop(self):
        TranslateHotkey(on_fire=MagicMock()).stop()

class TestCombo:
    def test_fires(self):
        fire = MagicMock()
        h, mk, hb = _wire(fire, HotkeySpec(scan_code=18, ctrl=True, alt=True, mode="combo"))
        mk.is_pressed.side_effect = lambda k: k in ("ctrl", "alt")
        with patch("app.hotkey.keyboard", mk): h.start(); hb[0](_ev(18))
        fire.assert_called_once()
    def test_wrong_mods(self):
        fire = MagicMock()
        h, mk, hb = _wire(fire, HotkeySpec(scan_code=18, ctrl=True, alt=True, mode="combo"))
        with patch("app.hotkey.keyboard", mk): h.start(); hb[0](_ev(18))
        fire.assert_not_called()
    def test_wrong_key(self):
        fire = MagicMock()
        h, mk, hb = _wire(fire, HotkeySpec(scan_code=18, ctrl=True, alt=True, mode="combo"))
        mk.is_pressed.side_effect = lambda k: k in ("ctrl", "alt")
        with patch("app.hotkey.keyboard", mk): h.start(); hb[0](_ev(30))
        fire.assert_not_called()
    def test_key_up(self):
        fire = MagicMock()
        h, mk, hb = _wire(fire, HotkeySpec(scan_code=18, ctrl=True, alt=True, mode="combo"))
        mk.is_pressed.side_effect = lambda k: k in ("ctrl", "alt")
        with patch("app.hotkey.keyboard", mk): h.start(); hb[0](_ev(18, "up"))
        fire.assert_not_called()

class TestDoubleTap:
    def test_fires(self):
        fire = MagicMock()
        h, mk, hb = _wire(fire, HotkeySpec(scan_code=41, mode="double", ctrl=False, alt=False))
        with patch("app.hotkey.keyboard", mk): h.start(); hb[0](_ev(41)); hb[0](_ev(41))
        fire.assert_called_once()
    def test_single(self):
        fire = MagicMock()
        h, mk, hb = _wire(fire, HotkeySpec(scan_code=41, mode="double", ctrl=False, alt=False))
        with patch("app.hotkey.keyboard", mk): h.start(); hb[0](_ev(41))
        fire.assert_not_called()
    def test_slow(self):
        fire = MagicMock()
        h, mk, hb = _wire(fire, HotkeySpec(scan_code=41, mode="double", ctrl=False, alt=False))
        with patch("app.hotkey.keyboard", mk):
            h.start(); hb[0](_ev(41)); h._last_ts = time.perf_counter() - 1.0; hb[0](_ev(41))
        fire.assert_not_called()
    def test_wrong_key(self):
        fire = MagicMock()
        h, mk, hb = _wire(fire, HotkeySpec(scan_code=41, mode="double", ctrl=False, alt=False))
        with patch("app.hotkey.keyboard", mk): h.start(); hb[0](_ev(41)); hb[0](_ev(30))
        fire.assert_not_called()
    def test_triple_once(self):
        fire = MagicMock()
        h, mk, hb = _wire(fire, HotkeySpec(scan_code=41, mode="double", ctrl=False, alt=False))
        with patch("app.hotkey.keyboard", mk): h.start(); hb[0](_ev(41)); hb[0](_ev(41)); hb[0](_ev(41))
        assert fire.call_count == 1

class TestReconfigure:
    def test_restarts(self):
        mk = MagicMock(); mk.hook.return_value = "h"
        h = TranslateHotkey(on_fire=MagicMock(), spec=HotkeySpec())
        with patch("app.hotkey.keyboard", mk): h.start(); h.reconfigure(HotkeySpec(scan_code=30))
        assert h.spec.scan_code == 30 and mk.hook.call_count == 2
    def test_no_start(self):
        h = TranslateHotkey(on_fire=MagicMock())
        h.reconfigure(HotkeySpec(scan_code=30))
        assert h.spec.scan_code == 30
