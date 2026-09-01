"""One request to the AI backend, collected into a string.

Two backends, picked by settings.ai_provider:

* gateway — the Bottlerocket corporate gateway. A streaming chat call with the
  console printing removed: the UI wants the finished answer, not a live feed.
  `modes.search` stays False — we rely on what the model already knows and never
  send anything off to a search engine. Auth is the in-memory JWT (ai_token).

* gemini — the direct Google AI Studio API, for when the corporate network is
  out of reach (home). Plain JSON request/response (no SSE), auth is the
  encrypted-at-rest key from ai_secrets.

Every call is its own session; nothing is remembered between clicks.
"""

from __future__ import annotations

import http.client
import json
import time
import urllib.parse
import uuid

from . import ai_config, ai_secrets, ai_token, logutil, netcerts
from . import settings as st

STREAM_TIMEOUT = 120
MAX_ATTEMPTS = 3
RETRY_DELAYS = (1.5, 4.0)
RETRY_STATUSES = frozenset((408, 409, 425, 429, 500, 502, 503, 504))
NET_ERRORS = (http.client.HTTPException, OSError, EOFError)


class AiError(RuntimeError):
    """Something the user should see in the footer, in Russian."""


def _provider() -> str:
    return str(getattr(st.get(), "ai_provider", "gateway") or "gateway")


def available() -> tuple[bool, str]:
    """Can we ask anything right now?"""
    if _provider() == "gemini":
        if not ai_secrets.available():
            return False, "нет модуля cryptography"
        if not ai_secrets.get_key("gemini"):
            return False, "нет ключа Gemini"
        return True, ""
    if not ai_config.configured():
        return False, "нет ai.json"
    if not ai_token.present():
        return False, "нет токена"
    if not ai_token.alive():
        return False, "токен истёк"
    return True, ""


def _model() -> str:
    if _provider() == "gemini":
        return (
            (getattr(st.get(), "ai_gemini_model", "") or "").strip()
            or ai_config.gemini_model()
        )
    return (st.get().ai_model or "").strip() or ai_config.model() or "claude-opus-4-6"


def model() -> str:
    """Which model a request would use right now — for stamping saved answers."""
    return _model()


# ---------------------------------------------------------------- gateway


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
        ai_config.host(), timeout=timeout, context=netcerts.ssl_context()
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


def _ask_gateway(query: str, *, system: str, timeout: int) -> str:
    """The Bottlerocket path — the original streaming logic, unchanged."""
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


# ---------------------------------------------------------------- gemini


def _gemini_body(query: str, system: str) -> bytes:
    payload: dict = {
        "contents": [{"role": "user", "parts": [{"text": query}]}],
        "generationConfig": {"temperature": 0.4},
    }
    if system.strip():
        payload["systemInstruction"] = {"parts": [{"text": system.strip()}]}
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _gemini_open(timeout: int):
    """Swapped out in tests — the only socket for the Gemini path."""
    return http.client.HTTPSConnection(
        ai_config.gemini_host(), timeout=timeout, context=netcerts.ssl_context()
    )


def gemini_text(data: dict) -> str:
    """Pull the answer text out of a generateContent response."""
    try:
        candidates = data.get("candidates") or []
        if not candidates:
            return ""
        parts = (candidates[0].get("content") or {}).get("parts") or []
        return "".join(str(p.get("text") or "") for p in parts if isinstance(p, dict))
    except Exception:  # noqa: BLE001
        return ""


def _ask_gemini(query: str, *, system: str, timeout: int) -> str:
    key = ai_secrets.get_key("gemini")
    if not key:
        raise AiError("нет ключа Gemini")

    body = _gemini_body(query, system)
    path = ai_config.gemini_path().replace("{model}", urllib.parse.quote(_model()))
    sep = "&" if "?" in path else "?"
    full_path = f"{path}{sep}key={urllib.parse.quote(key)}"
    headers = {"Content-Type": "application/json"}
    attempt = 0
    last = "не отвечает"

    while attempt < MAX_ATTEMPTS:
        attempt += 1
        conn = None
        t0 = time.perf_counter()
        try:
            conn = _gemini_open(timeout)
            conn.request("POST", full_path, body=body, headers=headers)
            resp = conn.getresponse()
            raw = resp.read().decode("utf-8", errors="replace")

            if resp.status in (400, 401, 403):
                _close(conn)
                conn = None
                logutil.get().warning("gemini HTTP %s: %s", resp.status, raw[:200])
                if resp.status == 400:
                    raise AiError("Gemini отклонил запрос (400)")
                raise AiError("ключ Gemini не подошёл — проверь его в настройках")

            if resp.status != 200:
                _close(conn)
                conn = None
                logutil.get().warning("gemini HTTP %s: %s", resp.status, raw[:200])
                last = f"сервер вернул {resp.status}"
                if resp.status in RETRY_STATUSES and attempt < MAX_ATTEMPTS:
                    time.sleep(RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)])
                    continue
                raise AiError(last)

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {}
            text = gemini_text(data if isinstance(data, dict) else {})
            logutil.get().debug("gemini reply %d chars in %.1fs", len(text), time.perf_counter() - t0)
            _close(conn)
            conn = None
            if text.strip():
                return text
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
            logutil.get().warning("gemini network: %s: %s", type(exc).__name__, exc)
            last = "сеть не отвечает"
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)])
                continue
            raise AiError(last) from exc
        except Exception as exc:  # noqa: BLE001
            _close(conn)
            conn = None
            logutil.exc("ai_client.gemini")
            raise AiError(f"{type(exc).__name__}") from exc
        finally:
            _close(conn)

    raise AiError(last)


# ---------------------------------------------------------------- public


def check_gemini_key(key: str, timeout: int = 20) -> tuple[bool, str]:
    """Validate a Gemini API key without burning a generation: ask for the model list.

    Returns (ok, message). A 200 means the key works; 400/401/403 means Google
    rejected it. Network trouble is reported, not raised.
    """
    key = (key or "").strip()
    if not key:
        return False, "сначала вставь ключ"
    path = "/v1beta/models?key=" + urllib.parse.quote(key)
    conn = None
    try:
        conn = http.client.HTTPSConnection(
            ai_config.gemini_host(), timeout=timeout, context=netcerts.ssl_context()
        )
        conn.request("GET", path, headers={"Accept": "application/json"})
        resp = conn.getresponse()
        try:
            raw = resp.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            raw = ""
        if resp.status == 200:
            return True, "ключ работает ✓"
        if resp.status in (400, 401, 403):
            logutil.get().warning("gemini key check HTTP %s: %s", resp.status, raw[:160])
            return False, "ключ не подошёл — проверь его"
        return False, f"сервер вернул {resp.status}"
    except NET_ERRORS as exc:
        logutil.get().warning("gemini key check network: %s", exc)
        return False, "сеть не отвечает"
    except Exception as exc:  # noqa: BLE001
        logutil.exc("check_gemini_key")
        return False, type(exc).__name__
    finally:
        _close(conn)


def ask(query: str, *, system: str = "", timeout: int = STREAM_TIMEOUT) -> str:
    """Send one message, return the answer. Raises AiError with a Russian message."""
    ok, why = available()
    if not ok:
        raise AiError(why)
    if _provider() == "gemini":
        return _ask_gemini(query, system=system, timeout=timeout)
    return _ask_gateway(query, system=system, timeout=timeout)