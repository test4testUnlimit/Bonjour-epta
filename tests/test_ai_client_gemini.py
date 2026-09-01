"""ai_client gemini backend: availability gating + response parsing, no socket."""

import json
from unittest.mock import patch

import pytest

from app import ai_client


def _provider(value):
    return patch.object(ai_client, "_provider", return_value=value)


class TestAvailability:
    def test_gemini_needs_a_key(self):
        with _provider("gemini"), patch.object(
            ai_client.ai_secrets, "available", return_value=True
        ), patch.object(ai_client.ai_secrets, "get_key", return_value=""):
            ok, why = ai_client.available()
            assert not ok and "Gemini" in why

    def test_gemini_needs_cryptography(self):
        with _provider("gemini"), patch.object(
            ai_client.ai_secrets, "available", return_value=False
        ):
            ok, why = ai_client.available()
            assert not ok and "cryptography" in why

    def test_gemini_ready(self):
        with _provider("gemini"), patch.object(
            ai_client.ai_secrets, "available", return_value=True
        ), patch.object(ai_client.ai_secrets, "get_key", return_value="k"):
            assert ai_client.available() == (True, "")

    def test_gateway_path_unchanged(self):
        with _provider("gateway"), patch.object(
            ai_client.ai_config, "configured", return_value=False
        ):
            ok, why = ai_client.available()
            assert not ok and why == "нет ai.json"


class TestGeminiText:
    def test_pulls_the_answer(self):
        data = {
            "candidates": [
                {"content": {"parts": [{"text": "привет"}, {"text": " мир"}]}}
            ]
        }
        assert ai_client.gemini_text(data) == "привет мир"

    def test_empty_candidates(self):
        assert ai_client.gemini_text({}) == ""
        assert ai_client.gemini_text({"candidates": []}) == ""

    def test_garbage_is_not_a_crash(self):
        assert ai_client.gemini_text({"candidates": [{"content": None}]}) == ""


class _Resp:
    def __init__(self, status, payload):
        self.status = status
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw


class _Conn:
    def __init__(self, *responses):
        self._responses = list(responses)
        self.requests = []

    def request(self, method, path, body=None, headers=None):
        self.requests.append((method, path, body, headers))

    def getresponse(self):
        return self._responses.pop(0)

    def close(self):
        pass


def _gemini_live():
    return patch.object(ai_client, "available", return_value=(True, ""))


class TestAsk:
    def test_gemini_happy_path(self):
        conn = _Conn(_Resp(200, {"candidates": [{"content": {"parts": [{"text": "готово"}]}}]}))
        with _provider("gemini"), _gemini_live(), patch.object(
            ai_client, "_gemini_open", return_value=conn
        ), patch.object(ai_client.ai_secrets, "get_key", return_value="KEY"), patch.object(
            ai_client.ai_config, "gemini_path", return_value="/v1beta/models/{model}:generateContent"
        ), patch.object(ai_client.ai_config, "gemini_model", return_value="gemini-2.5-flash"), patch.object(
            ai_client.time, "sleep"
        ):
            assert ai_client.ask("привет", system="БУДЬ КРАТОК") == "готово"
        # key went into the query string, system prompt into the body
        path = conn.requests[0][1]
        body = conn.requests[0][2].decode("utf-8")
        assert "key=KEY" in path
        assert "gemini-2.5-flash" in path
        assert "systemInstruction" in body and "БУДЬ КРАТОК" in body

    def test_gemini_bad_key_is_not_retried(self):
        conn = _Conn(_Resp(403, {"error": {"message": "API key not valid"}}))
        with _provider("gemini"), _gemini_live(), patch.object(
            ai_client, "_gemini_open", return_value=conn
        ), patch.object(ai_client.ai_secrets, "get_key", return_value="BAD"):
            with pytest.raises(ai_client.AiError, match="ключ"):
                ai_client.ask("x")

    def test_gemini_500_is_retried(self):
        good = _Resp(200, {"candidates": [{"content": {"parts": [{"text": "со 2 раза"}]}}]})
        conn = _Conn(_Resp(500, {}), good)
        with _provider("gemini"), _gemini_live(), patch.object(
            ai_client, "_gemini_open", return_value=conn
        ), patch.object(ai_client.ai_secrets, "get_key", return_value="K"), patch.object(
            ai_client.ai_config, "gemini_path", return_value="/p/{model}"
        ), patch.object(ai_client.ai_config, "gemini_model", return_value="m"), patch.object(
            ai_client.time, "sleep"
        ):
            assert ai_client.ask("x") == "со 2 раза"

    def test_no_key_raises(self):
        with _provider("gemini"), _gemini_live(), patch.object(
            ai_client.ai_secrets, "get_key", return_value=""
        ):
            with pytest.raises(ai_client.AiError, match="Gemini"):
                ai_client.ask("x")


class _GetResp:
    def __init__(self, status, payload=None):
        self.status = status
        self._raw = json.dumps(payload or {}).encode("utf-8")

    def read(self):
        return self._raw


class _GetConn:
    def __init__(self, response):
        self._response = response
        self.requests = []

    def request(self, method, path, body=None, headers=None):
        self.requests.append((method, path, body, headers))

    def getresponse(self):
        return self._response

    def close(self):
        pass


def _open_key_check(conn):
    return patch.object(ai_client.http.client, "HTTPSConnection", return_value=conn)


class TestCheckGeminiKey:
    def test_empty_key_short_circuits(self):
        ok, msg = ai_client.check_gemini_key("   ")
        assert not ok and "вставь" in msg

    def test_200_means_the_key_works(self):
        conn = _GetConn(_GetResp(200, {"models": []}))
        with _open_key_check(conn), patch.object(
            ai_client.ai_config, "gemini_host", return_value="h"
        ):
            ok, msg = ai_client.check_gemini_key("KEY")
        assert ok and "работает" in msg
        assert "key=KEY" in conn.requests[0][1]

    def test_403_means_bad_key(self):
        conn = _GetConn(_GetResp(403, {"error": {}}))
        with _open_key_check(conn), patch.object(
            ai_client.ai_config, "gemini_host", return_value="h"
        ):
            ok, msg = ai_client.check_gemini_key("BAD")
        assert not ok and "не подошёл" in msg

    def test_network_error_is_reported_not_raised(self):
        class Dead(_GetConn):
            def getresponse(self):
                raise OSError("no route")

        with _open_key_check(Dead(None)), patch.object(
            ai_client.ai_config, "gemini_host", return_value="h"
        ):
            ok, msg = ai_client.check_gemini_key("K")
        assert not ok and "сеть" in msg
