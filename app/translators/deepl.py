"""DeepL API — free tier needs key from https://www.deepl.com/pro-api"""

from __future__ import annotations

import httpx

from .base import TranslateResult, Translator

FREE_URL = "https://api-free.deepl.com/v2/translate"
PRO_URL = "https://api.deepl.com/v2/translate"


class DeepLTranslator(Translator):
    id = "deepl"
    label = "DeepL"
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
                error="DeepL API key required (set in settings later)",
            )

        # DeepL target codes are uppercase; source optional.
        tgt = target.upper()
        # DeepL uses EN / EN-US / EN-GB etc.; map common short codes.
        if tgt == "EN":
            tgt = "EN-US"
        if tgt == "PT":
            tgt = "PT-PT"

        data: dict[str, str | list[str]] = {
            "text": [text],
            "target_lang": tgt,
        }
        if source and source != "auto":
            data["source_lang"] = source.upper()

        # Free keys end with :fx
        url = FREE_URL if api_key.endswith(":fx") else PRO_URL
        headers = {"Authorization": f"DeepL-Auth-Key {api_key}"}

        try:
            with httpx.Client(timeout=12.0, follow_redirects=True) as client:
                r = client.post(url, data=data, headers=headers)
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
                detected_source=(first.get("detected_source_language") or "").lower() or None,
                provider=self.id,
            )
        except Exception as exc:  # noqa: BLE001
            return TranslateResult(text="", provider=self.id, error=f"parse: {exc}")
