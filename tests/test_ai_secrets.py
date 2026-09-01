"""ai_secrets: the Gemini key is encrypted at rest and never stored as plaintext."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app import ai_secrets


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    # Point the secrets file at a temp dir and reset the cached Fernet.
    monkeypatch.setattr(ai_secrets, "SECRETS_PATH", tmp_path / "ai_secrets.json")
    ai_secrets._fernet = None
    ai_secrets._fernet_tried = False
    yield
    ai_secrets._fernet = None
    ai_secrets._fernet_tried = False


@pytest.mark.skipif(not ai_secrets.available(), reason="cryptography not installed")
class TestRoundTrip:
    def test_set_then_get_returns_the_key(self):
        ok, _ = ai_secrets.set_key("gemini", "AIzaSyDUMMY-key-1234567890")
        assert ok
        assert ai_secrets.get_key("gemini") == "AIzaSyDUMMY-key-1234567890"

    def test_plaintext_never_touches_the_disk(self):
        secret = "AIzaSyDUMMY-super-secret-key"
        ai_secrets.set_key("gemini", secret)
        raw = ai_secrets.SECRETS_PATH.read_text(encoding="utf-8")
        assert secret not in raw
        # and what IS there is a Fernet token (url-safe base64, starts with gAAAA)
        data = json.loads(raw)
        assert data["gemini"].startswith("gAAAA")

    def test_has_key(self):
        assert not ai_secrets.has_key("gemini")
        ai_secrets.set_key("gemini", "x" * 20)
        assert ai_secrets.has_key("gemini")

    def test_clear_removes_it(self):
        ai_secrets.set_key("gemini", "x" * 20)
        ai_secrets.clear_key("gemini")
        assert not ai_secrets.has_key("gemini")
        assert ai_secrets.get_key("gemini") == ""

    def test_empty_plaintext_clears(self):
        ai_secrets.set_key("gemini", "x" * 20)
        ok, _ = ai_secrets.set_key("gemini", "   ")
        assert ok and not ai_secrets.has_key("gemini")

    def test_key_hint_shows_only_the_tail(self):
        ai_secrets.set_key("gemini", "AIzaSyDUMMY-abcd1234")
        hint = ai_secrets.key_hint("gemini")
        assert hint.endswith("1234")
        assert "AIzaSyDUMMY" not in hint

    def test_tampered_ciphertext_is_not_a_crash(self):
        ai_secrets.set_key("gemini", "x" * 20)
        data = json.loads(ai_secrets.SECRETS_PATH.read_text(encoding="utf-8"))
        data["gemini"] = "gAAAAABgarbage-tampered"
        ai_secrets.SECRETS_PATH.write_text(json.dumps(data), encoding="utf-8")
        assert ai_secrets.get_key("gemini") == ""  # wrong key/tamper → absent, not a crash


class TestWithoutCrypto:
    def test_graceful_when_cryptography_missing(self, monkeypatch):
        monkeypatch.setattr(ai_secrets, "_get_fernet", lambda: None)
        monkeypatch.setattr(ai_secrets, "_fernet_tried", True)
        ok, msg = ai_secrets.set_key("gemini", "x" * 20)
        assert not ok and "cryptography" in msg