"""Bearer token for the AI gateway — memory only, never touches the disk.

The user grabs it with the same Chrome bookmarklet the RCBR CLI uses, which
leaves `RCBR|<bearer>|<ms_token>|<refresh>` in the clipboard. We parse that,
keep it in module state, and quietly renew it through the OAuth refresh grant
while the app runs. Close the app and the token is gone.
"""

from __future__ import annotations

import base64
import http.client
import json
import threading
import time
import urllib.parse

from . import ai_config, logutil, netcerts

# Renew when this little is left; the watcher wakes up this often.
RENEW_BELOW_S = 300
WATCH_EVERY_S = 60
# A token with no readable `exp` still deserves a guess rather than a refusal.
ASSUMED_LIFE_S = 3600

_lock = threading.RLock()
_bearer = ""
_ms = ""
_refresh_tok = ""
_expires_at = 0.0
_user = ""
_watcher: threading.Thread | None = None
_listeners: list = []


# ---------------------------------------------------------------- jwt


def decode_jwt_payload(token: str) -> dict | None:
    try:
        p = token.split(".")[1]
        p += "=" * (-len(p) % 4)
        data = json.loads(base64.urlsafe_b64decode(p))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


def token_info(token: str) -> tuple[int | None, str]:
    """Seconds left and display name, or (None, '') if the token is opaque."""
    d = decode_jwt_payload(token)
    if not d or "exp" not in d:
        return None, ""
    try:
        left = int(float(d["exp"]) - time.time())
    except Exception:  # noqa: BLE001
        return None, ""
    return left, str(d.get("name") or d.get("preferred_username") or "")


# ---------------------------------------------------------------- state


def bearer() -> str:
    with _lock:
        return _bearer


def ms_token() -> str:
    with _lock:
        return _ms


def user() -> str:
    with _lock:
        return _user


def seconds_left() -> int:
    with _lock:
        if not _bearer:
            return 0
        return max(0, int(_expires_at - time.time()))


def present() -> bool:
    """A token was pasted — it may still have expired."""
    with _lock:
        return bool(_bearer)


def alive() -> bool:
    return seconds_left() > 0


def can_renew() -> bool:
    with _lock:
        return bool(_refresh_tok) and ai_config.can_refresh()


def clear() -> None:
    global _bearer, _ms, _refresh_tok, _expires_at, _user
    with _lock:
        _bearer = _ms = _refresh_tok = _user = ""
        _expires_at = 0.0
    _notify()


def on_change(callback) -> None:
    """Called (off the UI thread) whenever the token state moves."""
    _listeners.append(callback)


def off_change(callback) -> None:
    """Windows that come and go must unsubscribe, or the list grows all session."""
    try:
        _listeners.remove(callback)
    except ValueError:
        pass


def _notify() -> None:
    for cb in list(_listeners):
        try:
            cb()
        except Exception:  # noqa: BLE001
            logutil.exc("ai_token listener")


def apply_tokens(bearer_tok: str, ms: str = "", refresh: str = "") -> tuple[bool, str]:
    """Store a token set. Returns (ok, message for the user)."""
    global _bearer, _ms, _refresh_tok, _expires_at, _user
    bearer_tok = (bearer_tok or "").strip()
    if bearer_tok.lower().startswith("bearer "):
        bearer_tok = bearer_tok[7:].strip()
    if not bearer_tok:
        return False, "пустой токен"

    left, name = token_info(bearer_tok)
    if left is not None and left <= 0:
        return False, "токен уже истёк"

    with _lock:
        _bearer = bearer_tok
        if ms:
            _ms = ms.strip()
        if refresh:
            _refresh_tok = refresh.strip()
        _expires_at = time.time() + (left if left and left > 0 else ASSUMED_LIFE_S)
        if name:
            _user = name
        who = _user
        mins = max(0, int(_expires_at - time.time())) // 60

    _start_watcher()
    _notify()
    return True, f"{who} · {mins}м" if who else f"токен принят · {mins}м"


def paste_from_clipboard() -> tuple[bool, str]:
    """Read whatever the bookmarklet left in the clipboard."""
    try:
        import pyperclip

        clip = (pyperclip.paste() or "").strip()
    except Exception:  # noqa: BLE001
        logutil.exc("ai_token clipboard")
        return False, "не читается буфер обмена"

    if not clip:
        return False, "буфер обмена пуст"

    if clip.startswith("RCBR|"):
        parts = clip.split("|")
        if len(parts) < 2 or not parts[1]:
            return False, "в буфере обрезанные данные"
        return apply_tokens(
            parts[1],
            parts[2] if len(parts) > 2 else "",
            parts[3] if len(parts) > 3 else "",
        )

    # A bare JWT is fine too — three dot-separated base64 chunks, no spaces.
    bare = clip[7:].strip() if clip.lower().startswith("bearer ") else clip
    if bare.count(".") == 2 and " " not in bare and decode_jwt_payload(bare):
        return apply_tokens(bare)

    return False, "в буфере нет токена"


# ---------------------------------------------------------------- renew


def _post_form(host: str, path: str, body: str, headers: dict, timeout: int = 15) -> dict:
    """Injected wholesale in tests — nothing else here touches the network."""
    conn = http.client.HTTPSConnection(host, timeout=timeout, context=netcerts.ssl_context())
    try:
        conn.request("POST", path, body=body.encode("utf-8"), headers=headers)
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8", errors="replace")
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def renew(force: bool = False) -> bool:
    """Swap the bearer for a fresh one. force=True ignores the time check (hard 401)."""
    global _bearer, _ms, _refresh_tok, _expires_at, _user

    with _lock:
        rt = _refresh_tok
        left = max(0, int(_expires_at - time.time())) if _bearer else 0
    if not rt or not ai_config.can_refresh():
        return False
    if left > RENEW_BELOW_S and not force:
        return False

    o = ai_config.oauth()
    body = urllib.parse.urlencode(
        {
            "client_id": o.get("client_id", ""),
            "grant_type": "refresh_token",
            "refresh_token": rt,
            "scope": o.get("scope", ""),
        }
    )
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if ai_config.origin():
        headers["Origin"] = ai_config.origin()

    try:
        data = _post_form(
            str(o.get("host", "")),
            f"/{str(o.get('tenant', '')).strip('/')}/oauth2/v2.0/token",
            body,
            headers,
        )
    except Exception as exc:  # noqa: BLE001
        logutil.get().warning("ai_token renew failed: %s", exc)
        return False

    new = data.get("access_token")
    if not new:
        logutil.get().warning(
            "ai_token renew rejected: %s", str(data.get("error_description") or data.get("error"))[:120]
        )
        return False

    fresh, name = token_info(new)
    with _lock:
        _bearer = new
        _ms = data.get("id_token") or _ms
        _refresh_tok = data.get("refresh_token") or _refresh_tok
        _expires_at = time.time() + (fresh if fresh and fresh > 0 else ASSUMED_LIFE_S)
        if name:
            _user = name
    logutil.get().info("ai token renewed, %sm left", (fresh or ASSUMED_LIFE_S) // 60)
    _notify()
    return True


def _watch() -> None:
    while True:
        time.sleep(WATCH_EVERY_S)
        with _lock:
            if not _bearer:
                continue
        try:
            if seconds_left() <= RENEW_BELOW_S:
                if not renew() and not alive():
                    _notify()  # let the dot go red
        except Exception:  # noqa: BLE001
            logutil.exc("ai_token watcher")


def _start_watcher() -> None:
    global _watcher
    with _lock:
        if _watcher is not None and _watcher.is_alive():
            return
        _watcher = threading.Thread(target=_watch, name="ai-token", daemon=True)
        _watcher.start()
