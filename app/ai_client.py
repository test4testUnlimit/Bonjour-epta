"""One request to the AI gateway, streamed and collected into a string.

A port of the RCBR CLI's `stream_chat` with the console printing removed: the
UI wants the finished answer, not a live feed. `modes.search` stays False — we
rely on what the model already knows and never send anything off to a search
engine. Every call is its own session; nothing is remembered between clicks.
"""

from __future__ import annotations

import http.client
import json
import ssl
import time
import uuid

from . import ai_config, ai_token, logutil
from . import settings as st

STREAM_TIMEOUT = 120
MAX_ATTEMPTS = 3
RETRY_DELAYS = (1.5, 4.0)
RETRY_STATUSES = frozenset((408, 409, 425, 429, 500, 502, 503, 504))
NET_ERRORS = (http.client.HTTPException, OSError, EOFError)


class AiError(RuntimeError):
    """Something the user should see in the footer, in Russian."""


def available() -> tuple[bool, str]:
    """Can we ask anything right now?"""
    if not ai_config.configured():
        return False, "нет ai.json"
    if not ai_token.present():
        return False, "нет токена"
    if not ai_token.alive():
        return False, "токен истёк"
    return True, ""


def _model() -> str:
    return (st.get().ai_model or "").strip() or ai_config.model() or "claude-opus-4-6"


def model() -> str:
    """Which model a request would use right now — for stamping saved answers."""
    return _model()


def _body(query: str, system: str) -> bytes:
    full = f"{system.strip()}\n\n---\n{query}" if system.strip() else query
    payload = {
        "request": {
            "agent_slug": ai_config.agent_slug(),
            "model_slug": _model(),
            "locale": {"location": "America/Chicago", "language": "en-US"},
            "persona_id": "",
            "modes": {"search": False, "cowork_mode_enabled": False},
            "query": full,
        },
        "extra_data": {"origin": ai_config.origin()},
        "is_personalized": True,
        "stream": True,
    }
    # ensure_ascii=False — a Russian draft escaped to \uXXXX triples the payload.
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _headers() -> dict:
    h = {
        "Authorization": f"Bearer {ai_token.bearer()}",
        "x-ms-access-token": ai_token.ms_token(),
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "x-request-id": str(uuid.uuid4()),
    }
    origin = ai_config.origin()
    if origin:
        h["Origin"] = origin
        h["Referer"] = origin.rstrip("/") + "/"
    return h


def _open(timeout: int):
    """Swapped out in tests — the only place a socket is created."""
    return http.client.HTTPSConnection(
        ai_config.host(), timeout=timeout, context=ssl.create_default_context()
    )


def _close(conn) -> None:
    if conn is None:
        return
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass


def read_stream(resp) -> str:
    """Drain an SSE response into plain text. Reasoning deltas are dropped."""
    text = ""
    while True:
        raw = resp.readline()
        if not raw:
            break
        line = raw.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if chunk == "[DONE]":
            break
        try:
            evt = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if not isinstance(evt, dict):
            continue
        kind = evt.get("type", "")
        if kind == "text-delta":
            text += evt.get("delta", "") or ""
        elif kind == "error":
            msg = evt.get("errorText") or evt.get("error") or "stream error"
            logutil.get().warning("ai stream error: %s", str(msg)[:200])
    return text


def ask(query: str, *, system: str = "", timeout: int = STREAM_TIMEOUT) -> str:
    """Send one message, return the answer. Raises AiError with a Russian message."""
    ok, why = available()
    if not ok:
        raise AiError(why)

    ai_token.renew()  # cheap no-op unless the token is nearly out

    body = _body(query, system)
    headers_path = ai_config.path()
    tried_refresh = False
    attempt = 0
    last = "не отвечает"

    while attempt < MAX_ATTEMPTS:
        attempt += 1
        conn = None
        t0 = time.perf_counter()
        try:
            conn = _open(timeout)
            conn.request("POST", headers_path, body=body, headers=_headers())
            resp = conn.getresponse()

            if resp.status == 401:
                try:
                    resp.read()
                except Exception:  # noqa: BLE001
                    pass
                _close(conn)
                conn = None
                if not tried_refresh and ai_token.can_renew():
                    tried_refresh = True
                    if ai_token.renew(force=True):
                        attempt -= 1  # a refresh doesn't burn a retry
                        continue
                raise AiError("токен истёк — нажми 🔑 ещё раз")

            if resp.status != 200:
                try:
                    detail = resp.read().decode("utf-8", errors="replace")[:200]
                except Exception:  # noqa: BLE001
                    detail = ""
                _close(conn)
                conn = None
                logutil.get().warning("ai HTTP %s: %s", resp.status, detail)
                last = f"сервер вернул {resp.status}"
                if resp.status in RETRY_STATUSES and attempt < MAX_ATTEMPTS:
                    time.sleep(RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)])
                    continue
                raise AiError(last)

            text = read_stream(resp)
            logutil.get().debug("ai reply %d chars in %.1fs", len(text), time.perf_counter() - t0)
            if text.strip():
                return text
            _close(conn)
            conn = None
            last = "пустой ответ"
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)])
                continue
            raise AiError(last)

        except AiError:
            raise
        except NET_ERRORS as exc:
            _close(conn)
            conn = None
            logutil.get().warning("ai network: %s: %s", type(exc).__name__, exc)
            last = "сеть не отвечает"
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)])
                continue
            raise AiError(last) from exc
        except Exception as exc:  # noqa: BLE001
            _close(conn)
            conn = None
            logutil.exc("ai_client.ask")
            raise AiError(f"{type(exc).__name__}") from exc
        finally:
            _close(conn)

    raise AiError(last)
