"""ai_client: SSE parsing and the retry ladder, with no socket anywhere near."""

from unittest.mock import patch

import pytest

from app import ai_client


def sse(*lines):
    """A fake HTTPResponse that hands back one SSE line per readline()."""

    class Resp:
        status = 200

        def __init__(self):
            self._q = [(ln + "\n").encode("utf-8") for ln in lines]

        def readline(self):
            return self._q.pop(0) if self._q else b""

        def read(self):
            return b""

    return Resp()


class Conn:
    """Stands in for http.client.HTTPSConnection."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.requests = []

    def request(self, method, path, body=None, headers=None):
        self.requests.append((method, path, body, headers))

    def getresponse(self):
        return self._responses.pop(0)

    def close(self):
        pass


def _live():
    """Config + token present, so `available()` gets out of the way."""
    return patch.object(ai_client, "available", return_value=(True, ""))


def _run(conn, **kw):
    with _live(), patch.object(ai_client, "_open", return_value=conn), patch.object(
        ai_client.ai_token, "renew", return_value=False
    ), patch.object(ai_client.time, "sleep"):
        return ai_client.ask("привет", **kw)


class TestAvailability:
    def test_no_config_no_ask(self):
        with patch.object(ai_client.ai_config, "configured", return_value=False):
            ok, why = ai_client.available()
            assert not ok and why == "нет ai.json"
            with pytest.raises(ai_client.AiError):
                ai_client.ask("x")

    def test_no_token(self):
        with patch.object(ai_client.ai_config, "configured", return_value=True), patch.object(
            ai_client.ai_token, "present", return_value=False
        ):
            assert ai_client.available() == (False, "нет токена")

    def test_expired_token(self):
        with patch.object(ai_client.ai_config, "configured", return_value=True), patch.object(
            ai_client.ai_token, "present", return_value=True
        ), patch.object(ai_client.ai_token, "alive", return_value=False):
            assert ai_client.available() == (False, "токен истёк")


class TestStream:
    def test_deltas_are_glued_together(self):
        r = sse(
            'data: {"type":"start"}',
            'data: {"type":"text-delta","delta":"Hello"}',
            'data: {"type":"text-delta","delta":" world"}',
            "data: [DONE]",
        )
        assert ai_client.read_stream(r) == "Hello world"

    def test_done_stops_the_read(self):
        r = sse(
            'data: {"type":"text-delta","delta":"kept"}',
            "data: [DONE]",
            'data: {"type":"text-delta","delta":"dropped"}',
        )
        assert ai_client.read_stream(r) == "kept"

    def test_reasoning_is_thrown_away(self):
        r = sse(
            'data: {"type":"reasoning-delta","delta":"thinking"}',
            'data: {"type":"text-delta","delta":"answer"}',
            "data: [DONE]",
        )
        assert ai_client.read_stream(r) == "answer"

    def test_noise_between_events(self):
        r = sse(
            "event: message",
            "",
            ": keep-alive",
            "data: not json at all",
            'data: {"type":"text-delta","delta":"ok"}',
            "data: [DONE]",
        )
        assert ai_client.read_stream(r) == "ok"

    def test_server_error_event_is_logged_not_raised(self):
        r = sse('data: {"type":"error","errorText":"boom"}', "data: [DONE]")
        assert ai_client.read_stream(r) == ""

    def test_stream_that_just_ends(self):
        assert ai_client.read_stream(sse()) == ""


class TestAsk:
    def test_happy_path(self):
        conn = Conn(sse('data: {"type":"text-delta","delta":"готово"}', "data: [DONE]"))
        assert _run(conn) == "готово"
        assert conn.requests[0][0] == "POST"

    def test_system_prompt_rides_along(self):
        conn = Conn(sse('data: {"type":"text-delta","delta":"x"}', "data: [DONE]"))
        _run(conn, system="БУДЬ КРАТОК")
        body = conn.requests[0][2].decode("utf-8")
        assert "БУДЬ КРАТОК" in body
        assert '"search": false' in body.lower()

    def test_401_refreshes_once_then_succeeds(self):
        bad = sse()
        bad.status = 401
        conn = Conn(bad, sse('data: {"type":"text-delta","delta":"ок"}', "data: [DONE]"))
        with _live(), patch.object(ai_client, "_open", return_value=conn), patch.object(
            ai_client.ai_token, "renew", return_value=True
        ) as renew, patch.object(ai_client.ai_token, "can_renew", return_value=True):
            assert ai_client.ask("привет") == "ок"
        renew.assert_any_call(force=True)

    def test_401_without_a_refresh_token_gives_up(self):
        bad = sse()
        bad.status = 401
        conn = Conn(bad)
        with _live(), patch.object(ai_client, "_open", return_value=conn), patch.object(
            ai_client.ai_token, "renew", return_value=False
        ), patch.object(ai_client.ai_token, "can_renew", return_value=False):
            with pytest.raises(ai_client.AiError, match="токен"):
                ai_client.ask("привет")

    def test_500_is_retried(self):
        bad = sse()
        bad.status = 500
        conn = Conn(bad, sse('data: {"type":"text-delta","delta":"со второго раза"}', "data: [DONE]"))
        assert _run(conn) == "со второго раза"

    def test_400_is_not_retried(self):
        bad = sse()
        bad.status = 400
        conn = Conn(bad)
        with pytest.raises(ai_client.AiError, match="400"):
            _run(conn)

    def test_empty_stream_is_retried_then_reported(self):
        conn = Conn(sse(), sse(), sse())
        with pytest.raises(ai_client.AiError, match="пустой"):
            _run(conn)

    def test_network_error_is_retried(self):
        class Flaky(Conn):
            def __init__(self):
                super().__init__(sse('data: {"type":"text-delta","delta":"живой"}', "data: [DONE]"))
                self.first = True

            def getresponse(self):
                if self.first:
                    self.first = False
                    raise OSError("connection reset")
                return super().getresponse()

        assert _run(Flaky()) == "живой"

    def test_network_error_all_the_way_down(self):
        class Dead(Conn):
            def getresponse(self):
                raise OSError("no route to host")

        with pytest.raises(ai_client.AiError, match="сеть"):
            _run(Dead())
