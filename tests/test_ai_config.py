"""ai_config: no ai.json means the AI half of the app is simply absent."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app import ai_config


@pytest.fixture(autouse=True)
def clean():
    ai_config.reload()
    yield
    ai_config.reload()


def _with(path: Path):
    return patch.object(ai_config, "CONFIG_PATH", path)


class TestMissing:
    def test_nothing_configured(self, tmp_path):
        with _with(tmp_path / "nope.json"):
            assert ai_config.configured() is False
            assert ai_config.can_refresh() is False

    def test_every_getter_still_answers(self, tmp_path):
        with _with(tmp_path / "nope.json"):
            assert ai_config.host() == ""
            assert ai_config.path() == ""
            assert ai_config.origin() == ""
            assert ai_config.agent_slug() == ""
            assert ai_config.model() == ""
            assert ai_config.oauth() == {}

    def test_broken_json_is_not_a_crash(self, tmp_path):
        bad = tmp_path / "ai.json"
        bad.write_text("{ this is not json", encoding="utf-8")
        with _with(bad):
            assert ai_config.configured() is False


class TestPresent:
    def _write(self, tmp_path, data):
        p = tmp_path / "ai.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def test_reads_the_endpoint(self, tmp_path):
        p = self._write(
            tmp_path,
            {
                "host": "backend.example.com",
                "path": "/v2/agents/x/chats",
                "origin": "https://chat.example.com",
                "agent_slug": "x",
                "model": "claude-opus-4-6",
            },
        )
        with _with(p):
            assert ai_config.configured() is True
            assert ai_config.host() == "backend.example.com"
            assert ai_config.model() == "claude-opus-4-6"
            assert ai_config.can_refresh() is False  # no oauth block

    def test_half_a_config_is_no_config(self, tmp_path):
        p = self._write(tmp_path, {"host": "backend.example.com"})
        with _with(p):
            assert ai_config.configured() is False

    def test_oauth_enables_renewal(self, tmp_path):
        p = self._write(
            tmp_path,
            {
                "host": "h",
                "path": "/p",
                "oauth": {"host": "login.example.com", "tenant": "T", "client_id": "C"},
            },
        )
        with _with(p):
            assert ai_config.can_refresh() is True
            assert ai_config.oauth()["tenant"] == "T"

    def test_model_list_falls_back_to_the_builtin_one(self, tmp_path):
        p = self._write(tmp_path, {"host": "h", "path": "/p"})
        with _with(p):
            assert ai_config.models() == list(ai_config.DEFAULT_MODELS)

    def test_config_can_list_its_own_models(self, tmp_path):
        p = self._write(tmp_path, {"host": "h", "path": "/p", "models": ["a", " b ", ""]})
        with _with(p):
            assert ai_config.models() == ["a", "b"]

    def test_configured_model_is_always_offered(self, tmp_path):
        p = self._write(tmp_path, {"host": "h", "path": "/p", "model": "some-new-thing"})
        with _with(p):
            assert ai_config.models()[0] == "some-new-thing"

    def test_reload_picks_up_a_new_file(self, tmp_path):
        p = tmp_path / "ai.json"
        with _with(p):
            assert ai_config.configured() is False
            p.write_text(json.dumps({"host": "h", "path": "/p"}), encoding="utf-8")
            assert ai_config.configured() is False  # still cached
            ai_config.reload()
            assert ai_config.configured() is True
