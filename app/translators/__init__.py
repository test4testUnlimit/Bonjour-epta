"""Registry of translation providers.

Free paths (same idea as Crow Translate / QOnlineTranslator):
- Google gtx: translate.googleapis.com client=gtx — no key (default)
- Yandex web: translate.yandex.net/api/v1/tr.json/translate ucid+srv=android — no key
- MyMemory / LibreTranslate / Lingva-style public instances — no key (Libre public flaky)
- Bing web (Crow): scrape token from bing.com/translator → ttranslatev3 — not ported yet
- DuckDuckGo: unofficial MS proxy via duckduckgo.com/translation.js — no key

NOT free without key:
- DeepL official API (Crow never shipped free DeepL; needs pro-api key)

Cloud optional:
- Yandex Cloud / DeepL when api_key passed
"""

from __future__ import annotations

from .base import TranslateResult, Translator
from .deepl import DeepLTranslator
from .duckduckgo import DuckDuckGoTranslator
from .google_gtx import GoogleGtxTranslator
from .libretranslate import LibreTranslateTranslator
from .mymemory import MyMemoryTranslator
from .yandex import YandexTranslator

# Order = UI order. Google first (max free payload). Key engines last.
PROVIDERS: dict[str, Translator] = {
    p.id: p
    for p in (
        GoogleGtxTranslator(),
        DuckDuckGoTranslator(),
        MyMemoryTranslator(),
        YandexTranslator(),
        LibreTranslateTranslator(),
        DeepLTranslator(),
    )
}

DEFAULT_PROVIDER_ID = "google_gtx"


def get_provider(provider_id: str | None) -> Translator:
    return PROVIDERS.get(provider_id or DEFAULT_PROVIDER_ID, PROVIDERS[DEFAULT_PROVIDER_ID])


def list_providers() -> list[tuple[str, str, bool]]:
    """Return (id, label, needs_api_key) for UI combos."""
    return [(p.id, p.label, p.needs_api_key) for p in PROVIDERS.values()]


def translate(
    text: str,
    source: str = "auto",
    target: str = "ru",
    provider_id: str | None = None,
    api_key: str | None = None,
) -> TranslateResult:
    return get_provider(provider_id).translate(text, source=source, target=target, api_key=api_key)


__all__ = [
    "PROVIDERS",
    "DEFAULT_PROVIDER_ID",
    "TranslateResult",
    "Translator",
    "get_provider",
    "list_providers",
    "translate",
]
