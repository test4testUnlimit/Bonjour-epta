"""Registry of translation providers.

Sources (reliable / well-known):
- Google gtx: translate.googleapis.com (unofficial client endpoint, no key) — default, fastest free path
- MyMemory: api.mymemory.translated.net (official free public API)
- LibreTranslate: libretranslate.com (open-source; public instance flaky)
- DeepL: api-free.deepl.com / api.deepl.com (official, API key)
- Yandex: translate.api.cloud.yandex.net (official Yandex Cloud, API key)

DuckDuckGo: no stable public translate API; historically proxies Bing — skipped for v0.1.
"""

from __future__ import annotations

from .base import TranslateResult, Translator
from .deepl import DeepLTranslator
from .google_gtx import GoogleGtxTranslator
from .libretranslate import LibreTranslateTranslator
from .mymemory import MyMemoryTranslator
from .yandex import YandexTranslator

PROVIDERS: dict[str, Translator] = {
    p.id: p
    for p in (
        GoogleGtxTranslator(),
        MyMemoryTranslator(),
        LibreTranslateTranslator(),
        DeepLTranslator(),
        YandexTranslator(),
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
