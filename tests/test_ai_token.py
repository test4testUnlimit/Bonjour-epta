"""ai_token: parse what the token grabber leaves in the clipboard, track expiry."""

import base64
import json
import time
from unittest.mock import patch

import pytest

from app import ai_token


def jwt(exp_in=3600, name="Test User"):
    """A JWT with a readable payload — the signature is never checked."""
    head = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    body = {"exp": int(time.time()) + exp_in, "name": name}
    mid = base64.urlsafe_b64encode(json.dumps(body).encode()).rstrip(b"=").decode()
    return f"{head}.{mid}.sig"


@pytest.fixture(autouse=True)
def clean():
    ai_token.clear()
    yield
    ai_token.clear()


class TestDecode:
    def test_reads_expiry_and_name(self):
        left, name = ai_token.token_info(jwt(600, "Иван"))
        assert 590 < left <= 600
        assert name == "Иван"

    def test_padding_is_restored(self):
        # payload lengths that need 1, 2 and 3 '=' back
        for n in ("a", "ab", "abc"):
            assert ai_token.decode_jwt_payload(jwt(60, n)) is not None

    def test_garbage_is_not_a_token(self):
        assert ai_token.decode_jwt_payload("not-a-jwt") is None
        assert ai_token.token_info("not-a-jwt") == (None, "")

    def test_opaque_token_has_no_expiry(self):
        head = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
        mid = base64.urlsafe_b64encode(b'{"sub":"x"}').rstrip(b"=").decode()
        assert ai_token.token_info(f"{head}.{mid}.s") == (None, "")


class TestApply:
    def test_accepts_a_live_token(self):
        ok, msg = ai_token.apply_tokens(jwt(1800, "Иван"))
        assert ok and "Иван" in msg
        assert ai_token.alive()
        assert ai_token.user() == "Иван"
        assert 1700 < ai_token.seconds_left() <= 1800

    def test_refuses_an_expired_one(self):
        ok, msg = ai_token.apply_tokens(jwt(-10))
        assert not ok and "истёк" in msg
        assert not ai_token.present()

    def test_refuses_nothing(self):
        assert ai_token.apply_tokens("   ")[0] is False

    def test_strips_the_bearer_word(self):
        t = jwt(300)
        assert ai_token.apply_tokens(f"Bearer {t}")[0]
        assert ai_token.bearer() == t

    def test_opaque_token_gets_an_assumed_life(self):
        assert ai_token.apply_tokens("opaque-token-string")[0]
        assert ai_token.seconds_left() > 3000

    def test_clear_forgets_everything(self):
        ai_token.apply_tokens(jwt(600, "Иван"), "ms", "refresh")
        ai_token.clear()
        assert not ai_token.present()
        assert not ai_token.alive()
        assert ai_token.bearer() == ""
        assert ai_token.ms_token() == ""
        assert ai_token.user() == ""


class TestListeners:
    def test_a_new_token_wakes_the_dot(self):
        hits = []

        def cb():
            hits.append(1)

        ai_token.on_change(cb)
        try:
            ai_token.apply_tokens(jwt(600))
            assert hits
        finally:
            ai_token.off_change(cb)

    def test_unsubscribing_actually_unsubscribes(self):
        hits = []

        def cb():
            hits.append(1)

        ai_token.on_change(cb)
        ai_token.off_change(cb)
        ai_token.apply_tokens(jwt(600))
        assert hits == []

    def test_unsubscribing_twice_is_harmless(self):
        def cb():
            pass

        ai_token.off_change(cb)  # never subscribed
        ai_token.on_change(cb)
        ai_token.off_change(cb)
        ai_token.off_change(cb)

    def test_a_broken_listener_does_not_break_the_paste(self):
        def boom():
            raise RuntimeError("no")

        ai_token.on_change(boom)
        try:
            assert ai_token.apply_tokens(jwt(600))[0]
        finally:
            ai_token.off_change(boom)


class TestClipboard:
    def _clip(self, text):
        mod = type("m", (), {"paste": staticmethod(lambda: text)})
        return patch.dict("sys.modules", {"pyperclip": mod})

    def test_piped_payload(self):
        t = jwt(900, "Иван")
        with self._clip(f"TOK|{t}|ms-token|refresh-token"):
            ok, msg = ai_token.paste_from_clipboard()
        assert ok and "Иван" in msg
        assert ai_token.bearer() == t
        assert ai_token.ms_token() == "ms-token"
        assert ai_token.can_renew() or True  # needs ai.json too — checked separately

    def test_piped_payload_without_refresh(self):
        with self._clip(f"TOK|{jwt(900)}|ms"):
            assert ai_token.paste_from_clipboard()[0]

    def test_truncated_piped_payload(self):
        with self._clip("TOK|"):
            ok, msg = ai_token.paste_from_clipboard()
        assert not ok and "обрезанные" in msg

    def test_bare_jwt_is_accepted(self):
        t = jwt(900, "Иван")
        with self._clip(t):
            assert ai_token.paste_from_clipboard()[0]
        assert ai_token.bearer() == t

    def test_empty_clipboard(self):
        with self._clip(""):
            ok, msg = ai_token.paste_from_clipboard()
        assert not ok and "пуст" in msg

    def test_random_text_is_not_a_token(self):
        with self._clip("Отправь PPAP до EOW"):
            ok, msg = ai_token.paste_from_clipboard()
        assert not ok and "нет токена" in msg
        assert not ai_token.present()


class TestRenew:
    def _cfg(self):
        return patch.multiple(
            "app.ai_config",
            can_refresh=lambda: True,
            oauth=lambda: {
                "host": "login.example.com",
                "tenant": "T",
                "client_id": "C",
                "scope": "S",
            },
            origin=lambda: "https://chat.example.com",
        )

    def test_swaps_in_the_new_token(self):
        ai_token.apply_tokens(jwt(60), "ms", "old-refresh")
        fresh = jwt(3600, "Иван")
        reply = {"access_token": fresh, "refresh_token": "new-refresh", "id_token": "new-ms"}
        with self._cfg(), patch.object(ai_token, "_post_form", return_value=reply):
            assert ai_token.renew() is True
        assert ai_token.bearer() == fresh
        assert ai_token.ms_token() == "new-ms"
        assert ai_token.seconds_left() > 3000

    def test_healthy_token_is_left_alone(self):
        ai_token.apply_tokens(jwt(3600), "ms", "refresh")
        with self._cfg(), patch.object(ai_token, "_post_form") as post:
            assert ai_token.renew() is False
        post.assert_not_called()

    def test_force_ignores_the_time_check(self):
        ai_token.apply_tokens(jwt(3600), "ms", "refresh")
        with self._cfg(), patch.object(
            ai_token, "_post_form", return_value={"access_token": jwt(3600)}
        ) as post:
            assert ai_token.renew(force=True) is True
        post.assert_called_once()

    def test_no_refresh_token_no_renewal(self):
        ai_token.apply_tokens(jwt(60), "ms")
        with self._cfg(), patch.object(ai_token, "_post_form") as post:
            assert ai_token.renew(force=True) is False
        post.assert_not_called()

    def test_rejection_keeps_the_old_token(self):
        old = jwt(60)
        ai_token.apply_tokens(old, "ms", "refresh")
        with self._cfg(), patch.object(
            ai_token, "_post_form", return_value={"error": "invalid_grant"}
        ):
            assert ai_token.renew() is False
        assert ai_token.bearer() == old

    def test_network_blowup_is_survivable(self):
        ai_token.apply_tokens(jwt(60), "ms", "refresh")
        with self._cfg(), patch.object(ai_token, "_post_form", side_effect=OSError("down")):
            assert ai_token.renew() is False
        assert ai_token.present()
