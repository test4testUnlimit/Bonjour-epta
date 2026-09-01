"""Encrypted-at-rest storage for external AI keys (Gemini & friends).

Why this exists: the Bottlerocket gateway token is a short-lived JWT that lives
in memory only and simply dies with the app. A personal Google AI Studio key is
different — it is long-lived and the user wants to paste it once at home and
forget it. Writing it to disk in plaintext is how keys end up in screenshots,
backups and git. So we encrypt it.

Scheme: Fernet (AES-128-CBC + HMAC-SHA256, from the `cryptography` package).
The Fernet key is derived with PBKDF2-HMAC-SHA256 from a stable per-machine
seed (on Windows: HKLM\\...\\Cryptography\\MachineGuid), so the ciphertext is
useless on any other machine and the app never asks for a passphrase.

The ciphertext lives in ~/.bonjur-epta/ai_secrets.json — the whole folder is
outside the repo and ai.json is already git-ignored, so the key cannot leak
into git or a release. It is decrypted into memory only for the duration of a
request and never written to logs.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import threading
from pathlib import Path

from . import logutil

SECRETS_PATH = Path.home() / ".bonjur-epta" / "ai_secrets.json"
_PBKDF2_ROUNDS = 200_000
_SALT = b"bonjur-epta/ai-secrets/v1"  # not a secret — just domain separation

_lock = threading.Lock()
_fernet = None
_fernet_tried = False


# ---------------------------------------------------------------- key


def _machine_seed() -> bytes:
    """A stable per-machine/per-user value. Not secret on its own — it only
    stops the ciphertext from being copy-paste useful on another box."""
    if sys.platform == "win32":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography"
            )
            val, _ = winreg.QueryValueEx(key, "MachineGuid")
            if val:
                return str(val).encode("utf-8")
        except Exception:  # noqa: BLE001
            pass
    # Fallback: user + host. Weaker, but still better than plaintext.
    return f"{os.getlogin() if hasattr(os, 'getlogin') else ''}@{os.uname().nodename if hasattr(os, 'uname') else ''}".encode(
        "utf-8"
    )


def _get_fernet():
    """Build the Fernet instance lazily; None if cryptography is missing."""
    global _fernet, _fernet_tried
    with _lock:
        if _fernet_tried:
            return _fernet
        _fernet_tried = True
        try:
            from cryptography.fernet import Fernet

            dk = hashlib.pbkdf2_hmac(
                "sha256", _machine_seed(), _SALT, _PBKDF2_ROUNDS, dklen=32
            )
            _fernet = Fernet(base64.urlsafe_b64encode(dk))
        except Exception:  # noqa: BLE001
            logutil.exc("ai_secrets: cannot init Fernet (cryptography installed?)")
            _fernet = None
        return _fernet


def available() -> bool:
    """True when encryption is usable (cryptography importable)."""
    return _get_fernet() is not None


# ---------------------------------------------------------------- file


def _read() -> dict:
    try:
        if SECRETS_PATH.is_file():
            data = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:  # noqa: BLE001
        logutil.exc("ai_secrets: cannot read %s" % SECRETS_PATH)
    return {}


def _write(data: dict) -> bool:
    try:
        SECRETS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SECRETS_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # Best effort: restrict to the owner (POSIX). On Windows this is a no-op
        # and the file already sits under the user's own profile.
        try:
            os.chmod(SECRETS_PATH, 0o600)
        except Exception:  # noqa: BLE001
            pass
        return True
    except Exception:  # noqa: BLE001
        logutil.exc("ai_secrets: cannot write %s" % SECRETS_PATH)
        return False


# ---------------------------------------------------------------- api


def set_key(provider: str, plaintext: str) -> tuple[bool, str]:
    """Encrypt and store a key. Returns (ok, message)."""
    plaintext = (plaintext or "").strip()
    if not plaintext:
        return clear_key(provider)
    f = _get_fernet()
    if f is None:
        return False, "нет модуля cryptography — ключ не сохранён"
    try:
        token = f.encrypt(plaintext.encode("utf-8")).decode("ascii")
    except Exception:  # noqa: BLE001
        logutil.exc("ai_secrets: encrypt")
        return False, "не удалось зашифровать ключ"
    data = _read()
    data[provider] = token
    if not _write(data):
        return False, "не удалось записать файл"
    return True, "ключ сохранён (зашифрован)"


def get_key(provider: str) -> str:
    """Decrypt into memory. '' when absent or undecryptable (e.g. other PC)."""
    token = _read().get(provider)
    if not token:
        return ""
    f = _get_fernet()
    if f is None:
        return ""
    try:
        return f.decrypt(str(token).encode("ascii")).decode("utf-8").strip()
    except Exception:  # noqa: BLE001
        # Wrong machine, corrupted file, or tampered — treat as absent, not a crash.
        logutil.get().warning("ai_secrets: cannot decrypt key for %s", provider)
        return ""


def has_key(provider: str) -> bool:
    return bool(_read().get(provider))


def clear_key(provider: str) -> tuple[bool, str]:
    data = _read()
    if provider in data:
        data.pop(provider)
        _write(data)
    return True, "ключ удалён"


def key_hint(provider: str) -> str:
    """Last-4 tail for the UI, without ever decrypting into a widget."""
    if not has_key(provider):
        return ""
    k = get_key(provider)
    return f"…{k[-4:]}" if len(k) >= 4 else "…"