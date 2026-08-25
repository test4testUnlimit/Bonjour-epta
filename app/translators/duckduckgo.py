"""DuckDuckGo — Microsoft translator proxy, no API key (unofficial).

Flow (pagetranslate / ddgs):
  1) GET duckduckgo.com?q=translate → extract vqd token
  2) POST duckduckgo.com/translation.js?vqd=…&query=translate&to=…
     body = plain UTF-8 text
"""

from __future__ import annotations

import re

import httpx

from .. import netcerts
from .base import TranslateResult, Translator

VQD_URL = "https://duckduckgo.com/"
TRANSLATE_URL = "https://duckduckgo.com/translation.js"
VQD_RE = re.compile(r"""vqd=['"]?(\d[\w-]+)""", re.IGNORECASE)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class DuckDuckGoTranslator(Translator):
    id = "duckduckgo"
    label = "DuckDuckGo"
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

        headers = {"User-Agent": UA}
        try:
            with netcerts.client(timeout=14.0, follow_redirects=True) as client:
                vqd = self._fetch_vqd(client, headers)
                params: dict[str, str] = {
                    "vqd": vqd,
                    "query": "translate",
                    "to": target or "ru",
                }
                if source and source != "auto":
                    params["from"] = source

                r = client.post(
                    TRANSLATE_URL,
                    params=params,
                    headers={
                        **headers,
                        "Content-Type": "text/plain; charset=UTF-8",
                    },
                    content=text.encode("utf-8"),
                )
                if r.status_code == 403:
                    # token expired — one retry with fresh vqd
                    vqd = self._fetch_vqd(client, headers)
                    params["vqd"] = vqd
                    r = client.post(
                        TRANSLATE_URL,
                        params=params,
                        headers={
                            **headers,
                            "Content-Type": "text/plain; charset=UTF-8",
                        },
                        content=text.encode("utf-8"),
                    )
                r.raise_for_status()
                data = r.json()
        except Exception as exc:  # noqa: BLE001
            return TranslateResult(text="", provider=self.id, error=str(exc))

        try:
            out = (data.get("translated") or data.get("translation") or "").strip()
            if not out:
                return TranslateResult(
                    text="",
                    provider=self.id,
                    error=data.get("error") or "empty translation",
                )
            detected = data.get("detected_language") or data.get("from")
            if detected:
                detected = str(detected).lower().split("-")[0]
            return TranslateResult(
                text=out,
                detected_source=detected,
                provider=self.id,
            )
        except Exception as exc:  # noqa: BLE001
            return TranslateResult(text="", provider=self.id, error=f"parse: {exc}")

    def _fetch_vqd(self, client: httpx.Client, headers: dict[str, str]) -> str:
        for method, kwargs in (
            ("GET", {"params": {"q": "translate", "ia": "web"}}),
            ("POST", {"data": {"q": "translate"}}),
        ):
            r = client.request(method, VQD_URL, headers=headers, **kwargs)
            r.raise_for_status()
            m = VQD_RE.search(r.text)
            if m:
                return m.group(1)
        raise ValueError("vqd token not found")
