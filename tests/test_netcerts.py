"""The corporate-proxy root lives in the OS store; certifi alone is not enough."""

from __future__ import annotations

import ssl

from app import netcerts


def test_context_is_cached_and_verifying():
    ctx = netcerts.ssl_context()
    assert ctx is netcerts.ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_context_carries_os_trust_store():
    # Anything less than a handful of roots means load_default_certs() was
    # skipped and we are back to certifi-only — the failure this module exists for.
    assert len(netcerts.ssl_context().get_ca_certs()) > 10


def test_client_verifies_against_that_context():
    created = {}

    class FakeClient:
        def __init__(self, **kw):
            created.update(kw)

    import httpx

    real = httpx.Client
    httpx.Client = FakeClient
    try:
        netcerts.client(timeout=1.0)
    finally:
        httpx.Client = real
    assert created["verify"] is netcerts.ssl_context()
    assert created["timeout"] == 1.0


def test_client_respects_explicit_verify():
    created = {}

    class FakeClient:
        def __init__(self, **kw):
            created.update(kw)

    import httpx

    real = httpx.Client
    httpx.Client = FakeClient
    try:
        netcerts.client(verify=False)
    finally:
        httpx.Client = real
    assert created["verify"] is False


def test_install_exports_bundle_for_libraries_we_do_not_control(tmp_path, monkeypatch):
    monkeypatch.setattr(netcerts, "_installed", False)
    monkeypatch.setattr(netcerts, "_bundle_path", lambda: tmp_path / "ca" / "bundle.pem")
    for var in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        monkeypatch.delenv(var, raising=False)

    netcerts.install()

    bundle = tmp_path / "ca" / "bundle.pem"
    assert bundle.exists()
    assert "BEGIN CERTIFICATE" in bundle.read_text(encoding="ascii")
    import os

    assert os.environ["SSL_CERT_FILE"] == str(bundle)
    assert os.environ["REQUESTS_CA_BUNDLE"] == str(bundle)


def test_install_never_overrides_an_explicit_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(netcerts, "_installed", False)
    monkeypatch.setattr(netcerts, "_bundle_path", lambda: tmp_path / "bundle.pem")
    monkeypatch.setenv("SSL_CERT_FILE", "C:\\mine.pem")

    netcerts.install()

    import os

    assert os.environ["SSL_CERT_FILE"] == "C:\\mine.pem"


def test_install_can_be_switched_off(tmp_path, monkeypatch):
    monkeypatch.setattr(netcerts, "_installed", False)
    monkeypatch.setattr(netcerts, "_bundle_path", lambda: tmp_path / "bundle.pem")
    monkeypatch.setenv("BONJUR_NO_CERT_FIX", "1")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)

    netcerts.install()

    assert not (tmp_path / "bundle.pem").exists()
