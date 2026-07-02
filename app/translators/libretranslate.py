"""LibreTranslate public/self-hosted JSON API — https://github.com/LibreTranslate/LibreTranslate"""

from __future__ import annotations

import httpx

from .base import TranslateResult, Translator

# Public instance; may rate-limit. Prefer self-host later.
DEFAULT_URL = "https://libretranslate.com/translate"


class LibreTranslateTranslator(Translator):
    id = "libretranslate"
    label = "LibreTranslate"
    needs_api_key = False  # some instances require key
    supports_auto = True

    def __init__(self, base_url: str = DEFAULT_URL) -> None:
        self.base_url = base_url

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

        body: dict = {
            "q": text,
            "source": source or "auto",
            "target": target,
            "format": "text",
        }
        if api_key:
            body["api_key"] = api_key

        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                r = client.post(self.base_url, json=body)
                r.raise_for_status()
                data = r.json()
        except Exception as exc:  # noqa: BLE001
            return TranslateResult(text="", provider=self.id, error=str(exc))

        out = (data.get("translatedText") or "").strip()
        detected = None
        det = data.get("detectedLanguage")
        if isinstance(det, dict):
            detected = det.get("language")
        return TranslateResult(
            text=out,
            detected_source=str(detected) if detected else None,
            provider=self.id,
            error=None if out else "empty response",
        )
