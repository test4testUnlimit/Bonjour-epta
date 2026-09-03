"""The two things we actually ask the model for: polish a draft, explain a term.

Prompts live here so the transport stays dumb. Every answer comes back as JSON —
markdown is a lot harder to parse reliably than a three-key object, and the
model is happy to oblige. `_parse_json` still forgives a fenced block or a
sentence of preamble, because sometimes it isn't.

The two toolbar buttons are user-configurable: settings.ai_fn{1,2}_{title,prompt}
override the built-in POLISH/EXPLAIN below. Empty prompt = the built-in default.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import ai_client
from .acronyms import importer

MAX_INPUT = 6000  # a draft e-mail, not a novel

_COMMON = (
    "Отвечай одним сообщением. Не задавай встречных вопросов. "
    "Не добавляй ничего после JSON."
)

POLISH_PROMPT = (
    "Ты — редактор деловой переписки инженера. Пользователь пишет по-русски или на "
    "ломаном английском и хочет, чтобы мысль звучала ясно и профессионально "
    "по-английски.\n"
    "Сохрани смысл и все факты, ничего не выдумывай. Убери канцелярит и грубость, "
    "оставь живой рабочий тон — не превращай короткую записку в официальное письмо.\n"
    "Верни ТОЛЬКО JSON-объект такого вида:\n"
    '{"english": "улучшенный текст на английском", '
    '"russian": "точный русский перевод этого английского текста", '
    '"why": "1-3 предложения по-русски: что изменено и почему так яснее и профессиональнее"}\n'
    + _COMMON
)

EXPLAIN_PROMPT = (
    "Ты объясняешь русскоязычному инженеру, что значит английская фраза или "
    "выражение.\n"
    "Разбери: буквальный смысл, реальный смысл в рабочем контексте, откуда "
    "выражение взялось, насколько оно формально и когда его уместно "
    "употреблять. Если это идиома или культурная отсылка — скажи об этом прямо.\n"
    "Пиши по-русски, простым текстом, без markdown-заголовков, до 10 строк.\n"
    "Отвечай одним сообщением. Не задавай встречных вопросов."
)

ACRONYM_PROMPT = (
    "Ты — справочник по техническим и корпоративным сокращениям (производство, "
    "качество, метрология, автоматизация, ИТ).\n"
    "Дай все правдоподобные расшифровки сокращения. Не выдумывай: если "
    "сокращение тебе неизвестно, верни пустой список.\n"
    "Верни ТОЛЬКО JSON-массив, не более 5 элементов, самый вероятный первым:\n"
    '[{"expansion": "полная расшифровка по-английски", '
    '"ru": "перевод расшифровки на русский", '
    '"where": "одно предложение по-русски: где и зачем это применяют", '
    '"domain": ["quality"], "confidence": "high|medium|low"}]\n'
    "Поле domain — одно-два из: engineering, quality, metrology, manufacturing, "
    "automation, logistics, it, safety, hr, corp.\n" + _COMMON
)

# Built-in button labels — used when the user has not renamed a function.
DEFAULT_FN1_TITLE = "причесать"
DEFAULT_FN2_TITLE = "объясни"


def _settings_get(attr: str, default: str = "") -> str:
    """Read one AI-function field from settings; never raises (import order)."""
    try:
        from . import settings as cfg

        return str(getattr(cfg.get(), attr, default) or "").strip()
    except Exception:  # noqa: BLE001
        return default


def fn1_title() -> str:
    return _settings_get("ai_fn1_title", DEFAULT_FN1_TITLE) or DEFAULT_FN1_TITLE


def fn2_title() -> str:
    return _settings_get("ai_fn2_title", DEFAULT_FN2_TITLE) or DEFAULT_FN2_TITLE


def fn1_prompt() -> str:
    """Button 1 system prompt: the user's override, else the built-in polish."""
    return _settings_get("ai_fn1_prompt") or POLISH_PROMPT


def fn2_prompt() -> str:
    """Button 2 system prompt: the user's override, else the built-in explain."""
    return _settings_get("ai_fn2_prompt") or EXPLAIN_PROMPT


@dataclass
class Polished:
    english: str
    russian: str = ""
    why: str = ""


@dataclass
class Candidate:
    term: str
    expansion: str
    ru: str = ""
    where: str = ""
    domain: list[str] = field(default_factory=list)
    confidence: str = ""


# A fenced markdown block, language tag optional, contents in group 1.
# \x60 is the backtick: writing three of them literally here has a habit of
# getting mangled by whatever edits this file, and an empty pattern made
# _slices() raise IndexError on m.group(1) for EVERY reply — the parser was
# dead in all cases, not just fenced ones.
_FENCE = re.compile(r"\x60{3}(?:[a-zA-Z]+)?[ \t]*\n(.*?)\x60{3}", re.S)


def _parse_json(text: str):
    """Bare JSON, a fenced block, or JSON buried in prose. Junk → None."""
    raw = (text or "").strip()
    if not raw:
        return None

    for candidate in _slices(raw):
        try:
            return json.loads(candidate)
        except Exception:  # noqa: BLE001
            continue
    return None


def _slices(raw: str):
    yield raw
    m = _FENCE.search(raw)
    if m:
        yield m.group(1).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = raw.find(opener), raw.rfind(closer)
        if 0 <= i < j:
            yield raw[i : j + 1]


def _clip(text: str) -> str:
    text = (text or "").strip()
    return text[:MAX_INPUT]


# ---------------------------------------------------------------- calls


def polish(text: str) -> Polished:
    """Rough draft → professional English + Russian back-translation + why."""
    reply = ai_client.ask(_clip(text), system=fn1_prompt())
    data = _parse_json(reply)
    if isinstance(data, dict) and str(data.get("english") or "").strip():
        return Polished(
            english=str(data["english"]).strip(),
            russian=str(data.get("russian") or "").strip(),
            why=str(data.get("why") or "").strip(),
        )
    # The model answered in prose. Better a usable answer than an error.
    body = reply.strip()
    if not body:
        raise ai_client.AiError("пустой ответ")
    return Polished(english=body)


def explain_phrase(text: str) -> str:
    """What the phrase really means, in Russian."""
    reply = ai_client.ask(_clip(text), system=fn2_prompt()).strip()
    if not reply:
        raise ai_client.AiError("пустой ответ")
    return reply


def explain_acronym(term: str, context: str = "") -> list[Candidate]:
    """Candidate expansions for a term the local packs do not know."""
    term = (term or "").strip()
    if not term:
        return []
    query = f"Сокращение: {term}"
    if context.strip():
        query += f"\nОно встретилось в тексте:\n{_clip(context)}"

    data = _parse_json(ai_client.ask(query, system=ACRONYM_PROMPT))
    if isinstance(data, dict):
        data = data.get("candidates") or data.get("results") or [data]
    if not isinstance(data, list):
        return []

    out: list[Candidate] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        expansion = str(item.get("expansion") or "").strip()
        if not expansion:
            continue
        domain = item.get("domain")
        if isinstance(domain, str):
            domain = [domain]
        out.append(
            Candidate(
                term=term,
                expansion=expansion,
                ru=str(item.get("ru") or "").strip(),
                where=str(item.get("where") or "").strip(),
                domain=[str(d).strip() for d in (domain or []) if str(d).strip()][:3],
                confidence=str(item.get("confidence") or "").strip().lower(),
            )
        )
        if len(out) >= 5:
            break
    return out


def to_row(c: Candidate) -> importer.Row:
    """Candidate → the same Row the paste-a-table importer produces."""
    return importer.Row(
        term=c.term,
        expansion=c.expansion,
        notes=c.where,
        ru=c.ru,
        verdict="internal",  # unvetted by a human — stays on this machine
        reasons=["добавлено через ИИ"],
        domain=list(c.domain),
    )