"""Point-translation: selecting text in one pane highlights its counterpart.

The hard part is a word whose standalone translation differs from its in-context
rendering — "used" alone → «использовал», but inside "he's used to the idea" →
«привык». A bare substring match of the standalone translation then finds
nothing, and even Google's dictionary alternatives don't list the contextual
meaning.

So the strategy for short selections is sentence-anchored alignment:

1.  Expand the selection to its containing sentence and translate THAT. The
    engine renders the word correctly in context («used to» → «привык»).
2.  Find the translated sentence as a substring of the other pane — this almost
    always hits, because both panes came from the same engine on the same text.
3.  Inside that located sentence-span, map the selected WORD INDEX onto the
    target sentence's word list. Word-index mapping survives the word-order
    changes and length differences that break a naive char-proportional map
    ("used" is word #2 of the English sentence; «привык» is word #2 of the
    Russian one, even though their char offsets barely overlap).

Longer selections skip the sentence expansion (they ARE the context) and go
straight to candidate substring matching; a total miss falls back to
proportional positioning across the whole pane so the user still lands roughly
right instead of getting a bare "?".
"""

from __future__ import annotations

import re

from . import logutil
from . import translators as tr

TAG = "spotlight"
TAG_MISS = "spotlight_miss"

MAX_FRAGMENT = 300
# A selection this short (in words) uses sentence-anchored alignment. Longer
# ones are treated as self-contained context.
_WORD_SENTENCE_ANCHOR = 3
# Minimum stem length accepted by the morphological fallback. Shorter stems
# ("бы", "to") match half the text and are worse than a miss.
_MIN_STEM = 4

_SENT_END = re.compile(r"[.!?…\n]")
_WORD = re.compile(r"[A-Za-zА-Яа-яЁё0-9']+")


def normalize(text: str) -> str:
    return (text or "").strip()


def find_fragment(haystack: str, needle: str) -> tuple[int, int] | None:
    """Case-insensitive substring hit. Returns (start, end) char offsets or None."""
    if not haystack or not needle:
        return None
    idx = haystack.lower().find(needle.lower())
    if idx < 0:
        return None
    return idx, idx + len(needle)


def _word_count(text: str) -> int:
    return len(_WORD.findall(text or ""))


def _words_with_spans(text: str) -> list[tuple[int, int]]:
    """(start,end) char span of every word in text, in order."""
    return [(m.start(), m.end()) for m in _WORD.finditer(text or "")]


def sentence_span(text: str, start: int, end: int) -> tuple[int, int]:
    """Grow a char span out to its containing sentence boundaries."""
    n = len(text)
    start = max(0, min(start, n))
    end = max(start, min(end, n))
    a = start
    while a > 0 and not _SENT_END.search(text[a - 1]):
        a -= 1
    while a < end and text[a] in " \t":
        a += 1
    b = end
    while b < n and not _SENT_END.search(text[b]):
        b += 1
    if b < n:
        b += 1
    return a, b


def _stem(word: str) -> str:
    """Very light stem: lowercase, strip a common inflection tail."""
    w = (word or "").lower().strip()
    for suf in (
        "ения", "ение", "ость", "ами", "ями", "ого", "его", "ому", "ему",
        "ing", "ies", "ied", "ed", "es",
        "ать", "ять", "ить", "ают", "уют", "ает", "ит",
        "ой", "ый", "ий", "ая", "ое", "ые", "им", "ым", "ом", "ем",
        "ах", "ях", "ам", "ям", "ов", "ев", "ей", "s",
    ):
        if w.endswith(suf) and len(w) - len(suf) >= _MIN_STEM:
            return w[: len(w) - len(suf)]
    return w


def _find_word(haystack: str, needle: str) -> tuple[int, int] | None:
    if not haystack or not needle:
        return None
    m = re.search(r"(?<![\w])" + re.escape(needle) + r"(?![\w])", haystack, re.I)
    if not m:
        return None
    return m.start(), m.end()


def _find_stem(haystack: str, needle: str) -> tuple[int, int] | None:
    stem = _stem(needle)
    if len(stem) < _MIN_STEM:
        return None
    m = re.search(r"(?<![\w])[\w]*" + re.escape(stem) + r"[\w]*(?![\w])", haystack, re.I)
    if not m:
        return None
    return m.start(), m.end()


def _translate(text: str, source: str, target: str, provider_id: str | None):
    text = normalize(text)
    if not text:
        return None
    try:
        r = tr.translate(text[:MAX_FRAGMENT], source=source, target=target, provider_id=provider_id)
        return r if r.ok else None
    except Exception:  # noqa: BLE001
        logutil.exc("spotlight translate")
        return None


def candidates_for(text: str, source: str, target: str, provider_id: str | None) -> list[str]:
    """Main translation + dictionary alternatives (short fragments). '' on failure."""
    r = _translate(text, source, target, provider_id)
    if r is None:
        return []
    out: list[str] = []

    def add(s: str) -> None:
        s = normalize(s)
        if s and s.lower() not in {x.lower() for x in out}:
            out.append(s)

    add(r.text)
    if _word_count(text) <= 4:
        for alt in r.alternatives or []:
            add(alt)
        for ex in r.examples or []:
            add(getattr(ex, "word", ""))
    return out


def locate(haystack: str, candidates: list[str]) -> tuple[int, int] | None:
    """First candidate that lands, exact → whole-word → stem. Offsets or None."""
    if not haystack:
        return None
    for cand in candidates:
        hit = find_fragment(haystack, cand)
        if hit:
            return hit
    for cand in candidates:
        if _word_count(cand) == 1:
            hit = _find_word(haystack, cand)
            if hit:
                return hit
    for cand in candidates:
        if _word_count(cand) == 1:
            hit = _find_stem(haystack, cand)
            if hit:
                return hit
    return None


def proportional_span(sel_start: int, sel_end: int, src_len: int, tgt_len: int) -> tuple[int, int] | None:
    if src_len <= 0 or tgt_len <= 0 or sel_end <= sel_start:
        return None
    a = max(0.0, min(1.0, sel_start / src_len))
    b = max(0.0, min(1.0, sel_end / src_len))
    start, end = int(a * tgt_len), int(b * tgt_len)
    if end <= start:
        end = min(tgt_len, start + 1)
    return start, end


def snap_to_word(text: str, start: int, end: int) -> tuple[int, int]:
    n = len(text)
    start = max(0, min(start, n))
    end = max(start, min(end, n))
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
        start -= 1
    while end < n and (text[end].isalnum() or text[end] == "_"):
        end += 1
    return start, end


def _word_index_map(
    sel_start: int, sel_end: int, s0: int, s1: int,
    src_whole: str, tgt_whole: str, t0: int, t1: int,
) -> tuple[int, int] | None:
    """Map the selection onto the target sentence by WORD INDEX.

    "used" is the Nth word of the source sentence → highlight the Nth word of
    the target sentence. Survives word-order changes far better than a char
    proportion. The selection may span several source words; we take the target
    span from the first to the last mapped word.
    """
    src_words = _words_with_spans(src_whole[s0:s1])
    tgt_words = _words_with_spans(tgt_whole[t0:t1])
    if not src_words or not tgt_words:
        return None

    # which source-word indices does the selection cover?
    first = last = None
    for idx, (wa, wb) in enumerate(src_words):
        abs_a, abs_b = s0 + wa, s0 + wb
        if abs_b <= sel_start or abs_a >= sel_end:
            continue
        if first is None:
            first = idx
        last = idx
    if first is None:
        return None

    # clamp into the target word list (target may have fewer/more words)
    n_src, n_tgt = len(src_words), len(tgt_words)
    # scale the index range proportionally across the word counts
    ta = round(first * n_tgt / n_src)
    tb = round((last + 1) * n_tgt / n_src) - 1
    ta = max(0, min(ta, n_tgt - 1))
    tb = max(ta, min(tb, n_tgt - 1))
    start = t0 + tgt_words[ta][0]
    end = t0 + tgt_words[tb][1]
    return start, end


def align(
    sel_start: int,
    sel_end: int,
    src_whole: str,
    tgt_whole: str,
    source: str,
    target: str,
    provider_id: str | None,
) -> tuple[tuple[int, int] | None, bool]:
    """The public entry. Returns ((start,end) in tgt_whole, approximate)."""
    frag = normalize(src_whole[sel_start:sel_end])
    if not frag:
        return None, False

    # ── sentence-anchored path for short selections ──────────────────────
    if _word_count(frag) <= _WORD_SENTENCE_ANCHOR:
        s0, s1 = sentence_span(src_whole, sel_start, sel_end)
        sentence = src_whole[s0:s1]
        rsent = _translate(sentence, source, target, provider_id)
        if rsent is not None:
            tsentence = normalize(rsent.text)
            span = find_fragment(tgt_whole, tsentence)
            if span:
                t0, t1 = span
                hit = _word_index_map(sel_start, sel_end, s0, s1, src_whole, tgt_whole, t0, t1)
                if hit:
                    return hit, False
                # word-index failed (e.g. no words) — fall back to char proportion
                rel_a = (sel_start - s0) / max(1, s1 - s0)
                rel_b = (sel_end - s0) / max(1, s1 - s0)
                inner_a = t0 + int(rel_a * (t1 - t0))
                inner_b = t0 + int(rel_b * (t1 - t0))
                if inner_b <= inner_a:
                    inner_b = min(t1, inner_a + 1)
                return snap_to_word(tgt_whole, inner_a, inner_b), False

    # ── candidate substring path ─────────────────────────────────────────
    cands = candidates_for(frag, source, target, provider_id)
    hit = locate(tgt_whole, cands)
    if hit:
        return hit, False

    # ── proportional fallback across the whole pane ──────────────────────
    span = proportional_span(sel_start, sel_end, len(src_whole), len(tgt_whole))
    if span:
        return snap_to_word(tgt_whole, span[0], span[1]), True
    return None, False


def words_only(text: str) -> bool:
    """Heuristic: translatable prose, not a bare number/punct (those rarely map)."""
    return bool(re.search(r"[A-Za-zА-Яа-яЁё]", text or ""))