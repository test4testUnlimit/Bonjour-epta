"""Google Translate unofficial gtx endpoint — no API key, fast, personal use."""

from __future__ import annotations

import httpx

from .base import TranslateResult, Translator

# Public client endpoint used by many open-source clients (no key).
# Not an official Google Cloud product; rate-limits apply.
GTX_URL = "https://translate.googleapis.com/translate_a/single"


class GoogleGtxTranslator(Translator):
    id = "google_gtx"
    label = "Google (gtx)"
    needs_api_key = False
    supports_auto = True

    def translate(
        self,
        text: str,
        source: str = "auto",
        target: str = "ru",
        api_key: str | None = None,
    ) -> TranslateResult:
        text = (text or "").strip()
        if not text:
            return TranslateResult(text="", provider=self.id, error="empty text")

        params = {
            "client": "gtx",
            "sl": source or "auto",
            "tl": target,
            "dt": "t",
            "q": text,
        }
        try:
            with httpx.Client(timeout=12.0, follow_redirects=True) as client:
                r = client.get(GTX_URL, params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as exc:  # noqa: BLE001 — surface to UI
            return TranslateResult(text="", provider=self.id, error=str(exc))

        try:
            chunks = data[0] or []
            out = "".join(part[0] for part in chunks if part and part[0])
            detected = data[2] if len(data) > 2 else None
            if isinstance(detected, list):
                detected = detected[0] if detected else None
            return TranslateResult(
                text=out,
                detected_source=str(detected) if detected else None,
                provider=self.id,
            )
        except Exception as exc:  # noqa: BLE001
            return TranslateResult(text="", provider=self.id, error=f"parse: {exc}")
