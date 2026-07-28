"""Tests for app/settings.py and app/chip_styles.py."""
from __future__ import annotations
import json
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from app.settings import AppSettings, load, get, save, update, on_change, _lock, CONFIG_PATH
from app.chip_styles import get_style, STYLES, DEFAULT_STYLE_ID, ChipStyle
from app.win_hotkeys import HotkeySpec

# ── AppSettings ─────────────────────────────────────────────
class TestAppSettings:
    def test_defaults(self):
        s = AppSettings()
        assert s.instant_translate is True
        assert s.source_lang == "auto"
        assert s.target_lang == "ru"
        assert s.chivoblya_enabled is True
        assert s.close_to_tray is True

    def test_to_dict(self):
        d = AppSettings().to_dict()
        assert isinstance(d, dict)
        assert "provider_id" in d
        assert "hotkey" in d

    def test_from_dict_none(self):
        s = AppSettings.from_dict(None)
        assert s.target_lang == "ru"

    def test_from_dict_empty(self):
        s = AppSettings.from_dict({})
        assert s.target_lang == "ru"

    def test_from_dict_partial(self):
        s = AppSettings.from_dict({"target_lang": "de", "source_lang": "en"})
        assert s.target_lang == "de"
        assert s.source_lang == "en"
        assert s.chivoblya_enabled is True  # default

    def test_from_dict_bad_provider(self):
        s = AppSettings.from_dict({"provider_id": "nonexistent_api"})
        from app.translators import DEFAULT_PROVIDER_ID
        assert s.provider_id == DEFAULT_PROVIDER_ID

    def test_from_dict_bad_theme(self):
        s = AppSettings.from_dict({"ui_theme": "rainbow"})
        assert s.ui_theme == "light"

    def test_from_dict_bad_hotkey(self):
        s = AppSettings.from_dict({"hotkey": "not a dict"})
        assert isinstance(s.hotkey, dict)

    def test_roundtrip(self):
        s = AppSettings(target_lang="fr", source_lang="de")
        s2 = AppSettings.from_dict(s.to_dict())
        assert s2.target_lang == "fr"
        assert s2.source_lang == "de"

    def test_hotkey_spec(self):
        s = AppSettings()
        spec = s.hotkey_spec()
        assert isinstance(spec, HotkeySpec)

    def test_dangerous_hotkey_sanitized(self):
        s = AppSettings.from_dict({
            "hotkey": {"scan_code": 44, "ctrl": True, "alt": False,
                       "shift": False, "win": False, "mode": "combo"}
        })
        # Ctrl+Z should be sanitized to default
        spec = s.hotkey_spec()
        assert spec == HotkeySpec()

# ── load / save / update ────────────────────────────────────
class TestLoadSaveUpdate:
    def test_load_creates_default(self, tmp_path):
        fake_path = tmp_path / "settings.json"
        with patch("app.settings.CONFIG_PATH", fake_path), \
             patch("app.settings.CONFIG_DIR", tmp_path), \
             patch("app.settings._settings", None):
            s = load()
            assert s.target_lang == "ru"

    def test_save_creates_file(self, tmp_path):
        fake_path = tmp_path / "settings.json"
        with patch("app.settings.CONFIG_PATH", fake_path), \
             patch("app.settings.CONFIG_DIR", tmp_path), \
             patch("app.settings._settings", AppSettings()):
            save()
            assert fake_path.exists()
            data = json.loads(fake_path.read_text(encoding="utf-8"))
            assert data["target_lang"] == "ru"

    def test_update_changes_and_notifies(self, tmp_path):
        fake_path = tmp_path / "settings.json"
        cb = MagicMock()
        with patch("app.settings.CONFIG_PATH", fake_path), \
             patch("app.settings.CONFIG_DIR", tmp_path), \
             patch("app.settings._settings", None), \
             patch("app.settings._listeners", [cb]):
            s = update(target_lang="ja")
            assert s.target_lang == "ja"
            cb.assert_called_once()

    def test_load_corrupt_file(self, tmp_path):
        fake_path = tmp_path / "settings.json"
        fake_path.write_text("NOT JSON!!!", encoding="utf-8")
        with patch("app.settings.CONFIG_PATH", fake_path), \
             patch("app.settings.CONFIG_DIR", tmp_path), \
             patch("app.settings._settings", None):
            s = load()
            assert s.target_lang == "ru"  # falls back to defaults

# ── ChipStyles ──────────────────────────────────────────────
class TestChipStyles:
    def test_default_exists(self):
        s = get_style(DEFAULT_STYLE_ID)
        assert isinstance(s, ChipStyle)
        assert s.id == DEFAULT_STYLE_ID

    def test_all_styles_valid(self):
        for st in STYLES:
            assert st.bg.startswith("#")
            assert st.ink.startswith("#")
            assert isinstance(st.dual_action, bool)

    def test_unknown_id_returns_default(self):
        s = get_style(9999)
        assert s.id == DEFAULT_STYLE_ID

    def test_none_id_returns_default(self):
        s = get_style(None)
        assert s.id == DEFAULT_STYLE_ID

    def test_each_id_accessible(self):
        for st in STYLES:
            assert get_style(st.id).id == st.id