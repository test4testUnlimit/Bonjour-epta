"""TLS trust taken from the OS certificate store instead of certifi's snapshot.

Corporate networks terminate every https connection and re-sign it with their
own root. That root is pushed into the Windows store — and silently rotated
there — but it will never be inside certifi, so httpx (certifi by default) dies
with CERTIFICATE_VERIFY_FAILED while the browser next to it is perfectly happy.

Reading the live OS store at runtime means a rotated corporate CA needs no
action from anyone: the next launch simply picks up the new root.
"""

from __future__ import annotations

import os
import ssl
import threading
from pathlib import Path

_lock = threading.Lock()
_ctx: ssl.SSLContext | None = None
_installed = False


def _bundle_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "bonjur-epta"
    return base / "ca-bundle.pem"


def _build() -> ssl.SSLContext:
    # create_default_context() -> load_default_certs(), which on Windows walks
    # both the ROOT (trusted roots) and CA (intermediates) stores. That is where
    # the corporate MITM root lives.
    ctx = ssl.create_default_context()
    try:
        import certifi

        # Additive, not a replacement: keeps the public roots for machines whose
        # OS store is thin (fresh containers, some Linux images).
        ctx.load_verify_locations(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        pass
    return ctx


def ssl_context() -> ssl.SSLContext:
    """Shared verification context — OS trust store plus certifi as a safety net."""
    global _ctx
    with _lock:
        if _ctx is None:
            _ctx = _build()
        return _ctx


def client(**kwargs):
    """httpx.Client that verifies against the OS store. Use instead of httpx.Client."""
    import httpx

    kwargs.setdefault("verify", ssl_context())
    return httpx.Client(**kwargs)


def _write_bundle() -> Path | None:
    """Dump the trusted roots to a PEM so libraries we don't control can use it."""
    try:
        certs = ssl_context().get_ca_certs(binary_form=True)
    except Exception:  # noqa: BLE001
        return None
    if not certs:
        return None
    chunks = []
    for der in certs:
        try:
            chunks.append(ssl.DER_cert_to_PEM_cert(der))
        except Exception:  # noqa: BLE001
            continue
    if not chunks:
        return None
    path = _bundle_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        blob = "".join(chunks)
        # Rewrite only on change — the store shifts maybe twice a year.
        if not path.exists() or path.read_text(encoding="ascii", errors="ignore") != blob:
            path.write_text(blob, encoding="ascii")
    except Exception:  # noqa: BLE001
        return None
    return path


def install() -> None:
    """Point the whole process (and its children) at the OS trust store.

    Covers code paths that build their own connection and never see
    ssl_context(): requests/urllib3, pip inside the launcher, curl.
    Safe to call more than once; never raises.
    """
    global _installed
    if _installed:
        return
    _installed = True
    try:
        # Lets sites opt out if a bundle ever goes stale in a weird way.
        if os.environ.get("BONJUR_NO_CERT_FIX"):
            return
        path = _write_bundle()
        if path is None:
            return
        value = str(path)
        for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
            if not os.environ.get(var):
                os.environ[var] = value
    except Exception:  # noqa: BLE001
        pass
