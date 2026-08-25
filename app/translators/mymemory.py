"""MyMemory free public API — https://mymemory.translated.net/doc/spec.php"""

from __future__ import annotations

from .. import netcerts
from .base import TranslateResult, Translator

URL = "https://api.mymemory.translated.net/get"


class MyMemoryTranslator(Translator):
    id = "mymemory"
    label = "MyMemory"
    needs_api_key = False  # optional email/key for higher quota
    supports_auto = False  # needs explicit source; we map auto→en fallback

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

        src = "en" if source in (None, "", "auto") else source
        params: dict[str, str] = {
            "q": text[:500],  # free tier hard limit ~500 chars
            "langpair": f"{src}|{target}",
        }
        if api_key:
            params["key"] = api_key

        try:
            with netcerts.client(timeout=12.0, follow_redirects=True) as client:
                r = client.get(URL, params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as exc:  # noqa: BLE001
            return TranslateResult(text="", provider=self.id, error=str(exc))

        try:
            payload = data.get("responseData") or {}
            out = (payload.get("translatedText") or "").strip()
            status = data.get("responseStatus")
            if status and int(status) != 200 and not out:
                return TranslateResult(
                    text="",
                    provider=self.id,
                    error=data.get("responseDetails") or f"status {status}",
                )
            return TranslateResult(text=out, detected_source=src, provider=self.id)
        except Exception as exc:  # noqa: BLE001
            return TranslateResult(text="", provider=self.id, error=f"parse: {exc}")
