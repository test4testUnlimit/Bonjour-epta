from app import languages as L


class TestDirectionFollowsText:
    """ru→en fed English used to translate English into English — and kill the chip."""

    def test_pair_reverses_for_target_language_text(self):
        assert L.effective_target("en", "ru", "Loading furnace, 816 set") == "ru"

    def test_pair_keeps_direction_for_source_language_text(self):
        assert L.effective_target("en", "ru", "Привет мир") == "en"

    def test_auto_source_is_left_alone(self):
        assert L.effective_target("ru", "auto", "Привет мир") == "ru"

    def test_no_letters_no_opinion(self):
        assert L.effective_target("en", "ru", "12345 !!") == "en"

    def test_script_mismatch_and_counterpart(self):
        assert L.script_mismatch("en", "Привет") is True
        assert L.script_mismatch("ru", "Привет") is False
        assert L.counterpart("ru") == "en" and L.counterpart("en") == "ru"
