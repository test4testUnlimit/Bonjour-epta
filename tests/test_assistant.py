"""assistant: the model answers in JSON — usually. Parse it either way."""

from unittest.mock import patch

import pytest

from app import ai_client, assistant


def reply(text):
    return patch.object(assistant.ai_client, "ask", return_value=text)


class TestParseJson:
    def test_bare_object(self):
        assert assistant._parse_json('{"a": 1}') == {"a": 1}

    def test_bare_array(self):
        assert assistant._parse_json('[{"a": 1}]') == [{"a": 1}]

    def test_fenced(self):
        assert assistant._parse_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_fenced_without_a_language(self):
        assert assistant._parse_json('```\n{"a": 1}\n```') == {"a": 1}

    def test_wrapped_in_prose(self):
        raw = 'Конечно! Вот результат:\n{"a": 1}\nНадеюсь, помог.'
        assert assistant._parse_json(raw) == {"a": 1}

    def test_junk(self):
        assert assistant._parse_json("нет тут никакого json") is None

    def test_empty(self):
        assert assistant._parse_json("") is None
        assert assistant._parse_json(None) is None


class TestPolish:
    def test_three_fields(self):
        raw = (
            '{"english": "Please send the report by Friday.",'
            ' "russian": "Пожалуйста, пришлите отчёт до пятницы.",'
            ' "why": "Убрал двойное отрицание, добавил срок."}'
        )
        with reply(raw):
            p = assistant.polish("надо бы отчет не позже пятницы")
        assert p.english.startswith("Please send")
        assert "отчёт" in p.russian
        assert "срок" in p.why

    def test_fenced_answer(self):
        with reply('```json\n{"english": "Done.", "russian": "Готово."}\n```'):
            p = assistant.polish("сделано")
        assert p.english == "Done." and p.why == ""

    def test_prose_answer_is_still_usable(self):
        with reply("Here is a cleaner version: Please review the drawing."):
            p = assistant.polish("глянь чертеж")
        assert "Please review" in p.english
        assert p.russian == "" and p.why == ""

    def test_empty_answer_is_an_error(self):
        with reply("   "), pytest.raises(ai_client.AiError):
            assistant.polish("что-нибудь")

    def test_json_without_english_falls_back_to_prose(self):
        with reply('{"russian": "только перевод"}'):
            p = assistant.polish("текст")
        assert p.english == '{"russian": "только перевод"}'

    def test_long_input_is_clipped(self):
        with patch.object(assistant.ai_client, "ask", return_value='{"english":"x"}') as ask:
            assistant.polish("а" * 20000)
        assert len(ask.call_args[0][0]) == assistant.MAX_INPUT


class TestExplainPhrase:
    def test_plain_russian_comes_back_as_is(self):
        with reply("«Break a leg» — пожелание удачи перед выступлением."):
            assert "удачи" in assistant.explain_phrase("break a leg")

    def test_empty_is_an_error(self):
        with reply(""), pytest.raises(ai_client.AiError):
            assistant.explain_phrase("break a leg")


class TestExplainAcronym:
    def test_candidates(self):
        raw = (
            '[{"expansion": "Final Assembly", "ru": "Финальная сборка",'
            ' "where": "Последний участок линии.", "domain": ["manufacturing"],'
            ' "confidence": "high"},'
            ' {"expansion": "Failure Analysis", "ru": "Анализ отказов",'
            ' "where": "Разбор причин отказа.", "domain": "quality"}]'
        )
        with reply(raw):
            got = assistant.explain_acronym("FA", "FA line stopped")
        assert [c.expansion for c in got] == ["Final Assembly", "Failure Analysis"]
        assert got[0].confidence == "high"
        assert got[1].domain == ["quality"]  # a bare string is wrapped
        assert all(c.term == "FA" for c in got)

    def test_model_admits_it_does_not_know(self):
        with reply("[]"):
            assert assistant.explain_acronym("XGV") == []

    def test_object_wrapper_is_unwrapped(self):
        with reply('{"candidates": [{"expansion": "Bill of Materials"}]}'):
            got = assistant.explain_acronym("BOM")
        assert got[0].expansion == "Bill of Materials"

    def test_single_object_answer(self):
        with reply('{"expansion": "Bill of Materials", "ru": "Спецификация"}'):
            got = assistant.explain_acronym("BOM")
        assert got[0].ru == "Спецификация"

    def test_entries_without_an_expansion_are_dropped(self):
        with reply('[{"ru": "нет расшифровки"}, {"expansion": "Cycle Time"}]'):
            got = assistant.explain_acronym("CT")
        assert [c.expansion for c in got] == ["Cycle Time"]

    def test_no_more_than_five(self):
        raw = "[" + ",".join(f'{{"expansion": "E{i}"}}' for i in range(9)) + "]"
        with reply(raw):
            assert len(assistant.explain_acronym("X")) == 5

    def test_junk_answer(self):
        with reply("понятия не имею"):
            assert assistant.explain_acronym("XGV") == []

    def test_blank_term_never_asks(self):
        with patch.object(assistant.ai_client, "ask") as ask:
            assert assistant.explain_acronym("  ") == []
        ask.assert_not_called()

    def test_context_travels_with_the_question(self):
        with patch.object(assistant.ai_client, "ask", return_value="[]") as ask:
            assistant.explain_acronym("FA", "the FA line stopped")
        assert "FA line stopped" in ask.call_args[0][0]


class TestToRow:
    def test_becomes_an_importer_row(self):
        c = assistant.Candidate(
            term="FA",
            expansion="Final Assembly",
            ru="Финальная сборка",
            where="Последний участок линии.",
            domain=["manufacturing"],
        )
        row = assistant.to_row(c)
        assert row.term == "FA"
        assert row.notes == "Последний участок линии."
        assert row.ru == "Финальная сборка"
        assert row.verdict == "internal"  # unvetted — never leaves the machine

    def test_entry_keeps_the_russian(self):
        row = assistant.to_row(
            assistant.Candidate(term="FA", expansion="Final Assembly", ru="Финальная сборка")
        )
        entry = assistant.importer.to_entry(row, {}, default_domain=("user",))
        assert entry["ru"] == "Финальная сборка"
        assert entry["domain"] == ["user"]
