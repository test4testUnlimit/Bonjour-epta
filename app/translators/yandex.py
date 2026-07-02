"""Yandex Translate API v2 — needs IAM/API key from Yandex Cloud."""

from __future__ import annotations

import httpx

from .base import TranslateResult, Translator

URL = "https://translate.api.cloud.yandex.net/translate/v2/translate"


class YandexTranslator(Translator):
    id = "yandex"
    label = "Yandex"
    needs_api_key = True
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
        if not api_key:
            return TranslateResult(
                text="",
                provider=self.id,
                error="Yandex API key required (set in settings later)",
            )

        body: dict = {
            "texts": [text],
            "targetLanguageCode": target,
        }
        if source and source != "auto":
            body["sourceLanguageCode"] = source

        headers = {
            "Authorization": f"Api-Key {api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=12.0, follow_redirects=True) as client:
                r = client.post(URL, json=body, headers=headers)
                r.raise_for_status()
                payload = r.json()
        except Exception as exc:  # noqa: BLE001
            return TranslateResult(text="", provider=self.id, error=str(exc))

        try:
            translations = payload.get("translations") or []
            if not translations:
                return TranslateResult(text="", provider=self.id, error="no translations")
            first = translations[0]
            return TranslateResult(
                text=first.get("text") or "",
                detected_source=first.get("detectedLanguageCode"),
                provider=self.id,
            )
        except Exception as exc:  # noqa: BLE001
            return TranslateResult(text="", provider=self.id, error=f"parse: {exc}")
