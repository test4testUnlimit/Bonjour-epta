"""ai_config gemini getters: public defaults, overridable via ai.json."""

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


def _write(tmp_path, data):
    p = tmp_path / "ai.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


class TestDefaults:
    def test_public_endpoint_is_builtin(self, tmp_path):
        with _with(tmp_path / "none.json"):
            assert ai_config.gemini_host() == "generativelanguage.googleapis.com"
            assert "{model}" in ai_config.gemini_path()
            assert ai_config.gemini_model() == "gemini-2.5-flash"

    def test_model_list_is_builtin(self, tmp_path):
        with _with(tmp_path / "none.json"):
            models = ai_config.gemini_models()
            assert "gemini-2.5-flash" in models
            assert models  # non-empty


class TestOverrides:
    def test_gemini_block_overrides(self, tmp_path):
        p = _write(tmp_path, {"gemini": {"host": "proxy.example.com", "model": "gemini-3-pro"}})
        with _with(p):
            assert ai_config.gemini_host() == "proxy.example.com"
            assert ai_config.gemini_model() == "gemini-3-pro"

    def test_toplevel_gemini_model_is_used(self, tmp_path):
        p = _write(tmp_path, {"model": "gemini-2.5-pro"})
        with _with(p):
            assert ai_config.gemini_model() == "gemini-2.5-pro"

    def test_toplevel_nongemini_model_is_ignored(self, tmp_path):
        p = _write(tmp_path, {"model": "claude-opus-4-6"})
        with _with(p):
            assert ai_config.gemini_model() == "gemini-2.5-flash"

    def test_current_model_is_always_offered(self, tmp_path):
        p = _write(tmp_path, {"gemini": {"model": "gemini-experimental-x"}})
        with _with(p):
            assert ai_config.gemini_models()[0] == "gemini-experimental-x"