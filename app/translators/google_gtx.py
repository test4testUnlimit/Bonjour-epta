"""Google Translate unofficial gtx endpoint — max free payload (Crow-compatible)."""

from __future__ import annotations

import httpx

from .base import ExampleItem, TranslateResult, Translator

GTX_URL = "https://translate.googleapis.com/translate_a/single"


class GoogleGtxTranslator(Translator):
    id = "google_gtx"
    label = "Google"
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

        # dt flags (Crow): t=translation, bd=dict, md=defs, ex=examples,
        # at=alt translations, rm=translit, ss=synonyms, rw=see-also
        params: list[tuple[str, str]] = [
            ("client", "gtx"),
            ("ie", "UTF-8"),
            ("oe", "UTF-8"),
            ("sl", source or "auto"),
            ("tl", target),
            ("hl", target),
            ("dt", "t"),
            ("dt", "bd"),
            ("dt", "md"),
            ("dt", "ex"),
            ("dt", "at"),
            ("dt", "rm"),
            ("dt", "ss"),
            ("dt", "rw"),
            ("q", text),
        ]
        try:
            with httpx.Client(timeout=14.0, follow_redirects=True) as client:
                r = client.get(GTX_URL, params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as exc:  # noqa: BLE001
            return TranslateResult(text="", provider=self.id, error=str(exc))

        try:
            return self._parse(data)
        except Exception as exc:  # noqa: BLE001
            return TranslateResult(text="", provider=self.id, error=f"parse: {exc}")

    def _parse(self, data: list) -> TranslateResult:
        # [0] sentences: [[translated, original, translit?, source_translit?], ...]
        chunks = data[0] or []
        out_parts: list[str] = []
        translit_parts: list[str] = []
        for part in chunks:
            if not part:
                continue
            if part[0]:
                out_parts.append(part[0])
            if len(part) > 2 and part[2]:
                translit_parts.append(str(part[2]))

        out = "".join(out_parts)
        translit = "".join(translit_parts) or None

        detected = None
        if len(data) > 2 and data[2]:
            det = data[2]
            if isinstance(det, list):
                det = det[0] if det else None
            detected = str(det) if det else None

        alternatives: list[str] = []
        examples: list[ExampleItem] = []

        # [1] dictionary / translation options by part of speech
        # structure: [[pos, [synonyms], [[word, [meanings], ...], ...], ...], ...]
        if len(data) > 1 and data[1]:
            for speech_block in data[1]:
                if not speech_block or not isinstance(speech_block, list):
                    continue
                pos = str(speech_block[0] or "")
                # detailed word rows often at index 2
                rows = speech_block[2] if len(speech_block) > 2 else None
                if isinstance(rows, list):
                    for row in rows[:6]:
                        if not row or not isinstance(row, list) or not row[0]:
                            continue
                        word = str(row[0])
                        meanings: list[str] = []
                        if len(row) > 1 and isinstance(row[1], list):
                            meanings = [str(m) for m in row[1][:5] if m]
                        examples.append(ExampleItem(word=word, pos=pos, meanings=meanings))
                        if word not in alternatives and word != out:
                            alternatives.append(word)
                # flat synonym list at index 1
                syns = speech_block[1] if len(speech_block) > 1 else None
                if isinstance(syns, list):
                    for s in syns[:8]:
                        if s and str(s) not in alternatives and str(s) != out:
                            alternatives.append(str(s))

        # [5] sometimes alternative translations
        if len(data) > 5 and data[5]:
            try:
                for block in data[5]:
                    if not isinstance(block, list) or len(block) < 3:
                        continue
                    alts = block[2]
                    if not isinstance(alts, list):
                        continue
                    for alt_row in alts[:6]:
                        if isinstance(alt_row, list) and alt_row and alt_row[0]:
                            w = str(alt_row[0])
                            if w not in alternatives and w != out:
                                alternatives.append(w)
            except Exception:  # noqa: BLE001
                pass

        # cap chips for UI
        alternatives = alternatives[:8]
        examples = examples[:8]

        return TranslateResult(
            text=out,
            detected_source=detected,
            provider=self.id,
            alternatives=alternatives,
            examples=examples,
            translit=translit,
        )
