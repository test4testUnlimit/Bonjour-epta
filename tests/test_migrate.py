"""Migration must be boring: copy everything, break nothing, never run twice."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import migrate


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolated HOME so a real ~/.bonjour-epta is never touched by the suite."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    # the registry step is a no-op off Windows, but pin it anyway
    monkeypatch.setattr(migrate, "_fix_autostart", lambda: None)
    return tmp_path


def _seed_old(home: Path) -> Path:
    old = home / migrate.OLD_DIRNAME
    (old / "packs").mkdir(parents=True)
    (old / "settings.json").write_text(json.dumps({"target_lang": "de"}), encoding="utf-8")
    (old / "ai_secrets.json").write_text("cipher", encoding="utf-8")
    (old / "packs" / "local.json").write_text("[]", encoding="utf-8")
    (old / migrate.OLD_LOG).write_text("old log line\n", encoding="utf-8")
    (old / migrate.OLD_VBS).write_text("stale vbs", encoding="utf-8")
    return old


def test_copies_settings_secrets_and_packs(home):
    old = _seed_old(home)

    assert migrate.run() is True

    new = home / migrate.NEW_DIRNAME
    assert json.loads((new / "settings.json").read_text(encoding="utf-8"))["target_lang"] == "de"
    assert (new / "ai_secrets.json").read_text(encoding="utf-8") == "cipher"
    assert (new / "packs" / "local.json").is_file()
    # the old folder is a safety net — it must survive
    assert (old / "settings.json").is_file()


def test_log_is_renamed_and_vbs_is_not_copied(home):
    _seed_old(home)
    migrate.run()

    new = home / migrate.NEW_DIRNAME
    assert (new / migrate.NEW_LOG).read_text(encoding="utf-8") == "old log line\n"
    assert not (new / migrate.OLD_LOG).exists()
    assert not (new / migrate.OLD_VBS).exists()


def test_second_run_is_a_no_op(home):
    _seed_old(home)
    assert migrate.run() is True
    assert migrate.run() is False


def test_never_clobbers_a_newer_value(home):
    """User already ran the new build and changed a setting: keep their value."""
    _seed_old(home)
    new = home / migrate.NEW_DIRNAME
    new.mkdir(parents=True)
    (new / "settings.json").write_text(json.dumps({"target_lang": "fr"}), encoding="utf-8")

    migrate.run()

    kept = json.loads((new / "settings.json").read_text(encoding="utf-8"))
    assert kept["target_lang"] == "fr"


def test_fresh_install_just_marks_and_moves_on(home):
    assert migrate.run() is False
    assert (home / migrate.NEW_DIRNAME / migrate.MARKER).is_file()
    assert migrate.run() is False


def test_unreadable_source_does_not_raise(home, monkeypatch):
    _seed_old(home)

    def boom(*_a, **_kw):
        raise OSError("disk gone")

    monkeypatch.setattr(migrate.shutil, "copy2", boom)
    # degraded, not fatal
    assert migrate.run() is True