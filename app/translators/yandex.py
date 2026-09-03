"""Yandex Translate — free web endpoint (Crow / QOnlineTranslator style), no Cloud key.

Crow uses:
  POST https://translate.yandex.net/api/v1/tr.json/translate
       ?ucid=<uuid32hex>&srv=android&text=...&lang=<tgt|src-tgt>

Official Yandex Cloud API is optional fallback when api_key is provided.
"""

from __future__ import annotations

import uuid

from .. import netcerts
from .base import TranslateResult, Translator

WEB_URL = "https://translate.yandex.net/api/v1/tr.json/translate"
CLOUD_URL = "https://translate.api.cloud.yandex.net/translate/v2/translate"


class YandexTranslator(Translator):
    id = "yandex"
    label = "Yandex (free)"
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

        if api_key:
            return self._cloud(text, source, target, api_key)
        return self._web_free(text, source, target)

    def _web_free(self, text: str, source: str, target: str) -> TranslateResult:
        # Crow: random UUID without dashes (Id128)
        ucid = uuid.uuid4().hex
        if source and source != "auto":
            lang = f"{source}-{target}"
        else:
            lang = target

        params = {
            "ucid": ucid,
            "srv": "android",
            "text": text,
            "lang": lang,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Bonjour-epta/0.1 (desktop; QOnlineTranslator-compat)",
        }
        try:
            with netcerts.client(timeout=12.0, follow_redirects=True) as client:
                # Crow posts empty body; params in query
                r = client.post(WEB_URL, params=params, headers=headers, content=b"")
                r.raise_for_status()
                payload = r.json()
        except Exception as exc:  # noqa: BLE001
            return TranslateResult(text="", provider=self.id, error=str(exc))

        try:
            code = payload.get("code")
            if code not in (None, 200, 0):
                return TranslateResult(
                    text="",
                    provider=self.id,
                    error=payload.get("message") or f"yandex code {code}",
                )
            texts = payload.get("text") or []
            if not texts:
                return TranslateResult(text="", provider=self.id, error="no translations")
            detected = None
            lang = payload.get("lang") or ""
            if isinstance(lang, str) and "-" in lang:
                detected = lang.split("-", 1)[0]
            return TranslateResult(
                text=texts[0] if isinstance(texts[0], str) else str(texts[0]),
                detected_source=detected,
                provider=self.id,
            )
        except Exception as exc:  # noqa: BLE001
            return TranslateResult(text="", provider=self.id, error=f"parse: {exc}")

    def _cloud(self, text: str, source: str, target: str, api_key: str) -> TranslateResult:
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
            with netcerts.client(timeout=12.0, follow_redirects=True) as client:
                r = client.post(CLOUD_URL, json=body, headers=headers)
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
