# -*- coding: utf-8 -*-
"""Tests for app/win_hotkeys.py."""
from __future__ import annotations
import pytest
from app.win_hotkeys import (
    HotkeySpec, alt_letter_warning, check_reserved, sanitize_hotkey, _scan_label
)


class TestHotkeySpec:
    def test_defaults(self):
        s = HotkeySpec()
        assert s.scan_code == 18
        assert s.ctrl is True
        assert s.alt is True
        assert s.mode == "combo"

    def test_label_combo(self):
        assert HotkeySpec(scan_code=18, ctrl=True, alt=True, mode="combo").label() == "Ctrl+Alt+E"

    def test_label_double(self):
        lbl = HotkeySpec(scan_code=41, ctrl=False, alt=False, mode="double").label()
        assert "2" in lbl

    def test_to_from_dict(self):
        s = HotkeySpec(scan_code=30, ctrl=True, shift=True, alt=False, win=False, mode="combo")
        assert HotkeySpec.from_dict(s.to_dict()) == s

    def test_from_dict_none(self):
        assert HotkeySpec.from_dict(None) == HotkeySpec()

    def test_from_dict_empty(self):
        # empty dict is falsy in Python, so from_dict returns default
        s = HotkeySpec.from_dict({})
        assert s == HotkeySpec()

    def test_from_dict_bad_mode(self):
        assert HotkeySpec.from_dict({"mode": "triple", "scan_code": 41}).mode == "double"

    def test_mode_ru(self):
        assert HotkeySpec(mode="combo").mode_ru() != HotkeySpec(mode="double").mode_ru()


class TestScanLabel:
    def test_known(self):
        assert _scan_label(18) == "E"
        assert _scan_label(57) == "Space"

    def test_unknown(self):
        assert _scan_label(999) == "sc999"


class TestCheckReserved:
    def test_ctrl_alt_e_ok(self):
        assert check_reserved(HotkeySpec()) is None

    def test_ctrl_z_blocked(self):
        s = HotkeySpec(scan_code=44, ctrl=True, alt=False, mode="combo")
        assert check_reserved(s) is not None

    def test_ctrl_c_blocked(self):
        s = HotkeySpec(scan_code=46, ctrl=True, alt=False, mode="combo")
        assert check_reserved(s) is not None

    def test_ctrl_v_blocked(self):
        s = HotkeySpec(scan_code=47, ctrl=True, alt=False, mode="combo")
        assert check_reserved(s) is not None

    def test_win_blocked(self):
        s = HotkeySpec(scan_code=18, win=True, ctrl=False, alt=False, mode="combo")
        assert check_reserved(s) is not None

    def test_alt_f4_blocked(self):
        s = HotkeySpec(scan_code=62, alt=True, ctrl=False, mode="combo")
        assert check_reserved(s) is not None

    def test_bare_double_ok(self):
        s = HotkeySpec(scan_code=41, ctrl=False, alt=False, mode="double")
        assert check_reserved(s) is None

    def test_combo_no_mods_blocked(self):
        s = HotkeySpec(scan_code=18, ctrl=False, alt=False, shift=False, win=False, mode="combo")
        assert check_reserved(s) is not None


class TestSanitize:
    def test_good_passes(self):
        assert sanitize_hotkey(HotkeySpec()) == HotkeySpec()

    def test_bad_falls_to_default(self):
        s = HotkeySpec(scan_code=44, ctrl=True, alt=False, mode="combo")
        assert sanitize_hotkey(s) == HotkeySpec()

    def test_double_with_mods_becomes_combo(self):
        s = HotkeySpec(scan_code=18, ctrl=True, alt=True, mode="double")
        assert sanitize_hotkey(s).mode == "combo"

    def test_bare_double_kept(self):
        s = HotkeySpec(scan_code=41, ctrl=False, alt=False, mode="double")
        assert sanitize_hotkey(s) == s

class TestAltLetterWarning:
    """Alt+<letter> delivers its character on Alt-up while the key still
    auto-repeats. Warn, never rewrite — sanitize_hotkey would reset the
    binding the user chose."""

    def test_alt_c_is_flagged(self):
        # scan 46 = C, alt only — the user's live config
        spec = HotkeySpec(scan_code=46, ctrl=False, alt=True, mode="combo")
        assert "C" in (alt_letter_warning(spec) or "")

    def test_ctrl_alt_is_fine(self):
        assert alt_letter_warning(HotkeySpec(scan_code=46, ctrl=True, alt=True)) is None

    def test_alt_non_letter_is_fine(self):
        spec = HotkeySpec(scan_code=41, ctrl=False, alt=True)  # `/ё
        assert alt_letter_warning(spec) is None

    def test_warning_does_not_reset_the_binding(self):
        spec = HotkeySpec(scan_code=46, ctrl=False, alt=True, mode="combo")
        assert sanitize_hotkey(spec) == spec
