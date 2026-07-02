# Translation API sources (v0.1)

| ID | Label | Key? | Endpoint | Notes |
|---|---|---|---|---|
| `google_gtx` | Google (gtx) | no | `https://translate.googleapis.com/translate_a/single` | Unofficial client endpoint; auto-detect; **default**; fastest free path for prototype |
| `mymemory` | MyMemory | optional | `https://api.mymemory.translated.net/get` | Official free public API; ~500 char free limit; weak auto |
| `libretranslate` | LibreTranslate | sometimes | `https://libretranslate.com/translate` | Open-source; public instance flaky/rate-limited |
| `deepl` | DeepL | **yes** | `api-free.deepl.com` / `api.deepl.com` | Best quality; free key ends with `:fx` |
| `yandex` | Yandex | **yes** | `translate.api.cloud.yandex.net/translate/v2/translate` | Official Yandex Cloud |

**Skipped for v0.1:** DuckDuckGo — no stable documented public translate API (historically Bing proxy). Revisit if a reliable reverse-engineered client appears.

**Priority order for default:** Google gtx → MyMemory fallback later → keyed DeepL when user adds key.
