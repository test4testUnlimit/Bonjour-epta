"""Persistent settings — live apply, no restart."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import translators as tr
from .win_hotkeys import HotkeySpec, sanitize_hotkey

CONFIG_DIR = Path.home() / ".bonjur-epta"
CONFIG_PATH = CONFIG_DIR / "settings.json"


@dataclass
class AppSettings:
    instant_translate: bool = True
    provider_id: str = field(default_factory=lambda: tr.DEFAULT_PROVIDER_ID)
    source_lang: str = "auto"
    target_lang: str = "ru"
    show_examples: bool = False  # off by default; setting removed from UI
    chivoblya_enabled: bool = True
    autostart: bool = False
    close_to_tray: bool = True  # X / Alt+F4 → tray; tray «выход» always quits
    hotkey: dict = field(default_factory=lambda: HotkeySpec().to_dict())
    chip_style_id: int = 1  # see app/chip_styles.py — user picks in style window

    def hotkey_spec(self) -> HotkeySpec:
        raw = HotkeySpec.from_dict(self.hotkey if isinstance(self.hotkey, dict) else None)
        return sanitize_hotkey(raw)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> AppSettings:
        base = cls()
        if not data:
            return base
        for k in asdict(base):
            if k in data:
                setattr(base, k, data[k])
        if base.provider_id not in tr.PROVIDERS:
            base.provider_id = tr.DEFAULT_PROVIDER_ID
        if not isinstance(base.hotkey, dict):
            base.hotkey = HotkeySpec().to_dict()
        # drop illegal combos (e.g. Ctrl+Z×2 saved by mistake)
        safe = sanitize_hotkey(HotkeySpec.from_dict(base.hotkey))
        base.hotkey = safe.to_dict()
        return base


_lock = threading.Lock()
_settings: AppSettings | None = None
_listeners: list = []


def load() -> AppSettings:
    global _settings
    with _lock:
        if _settings is not None:
            return _settings
        data = None
        try:
            if CONFIG_PATH.is_file():
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            data = None
        _settings = AppSettings.from_dict(data if isinstance(data, dict) else None)
        return _settings


def get() -> AppSettings:
    return load()


def save(s: AppSettings | None = None) -> None:
    global _settings
    with _lock:
        if s is not None:
            _settings = s
        assert _settings is not None
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(_settings.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def update(**kwargs) -> AppSettings:
    s = load()
    for k, v in kwargs.items():
        if hasattr(s, k):
            setattr(s, k, v)
    save(s)
    for cb in list(_listeners):
        try:
            cb(s)
        except Exception:  # noqa: BLE001
            pass
    return s


def on_change(callback) -> None:
    _listeners.append(callback)
