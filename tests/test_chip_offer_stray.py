"""Chip offer — field signatures from 2026-08-09 BUGMARKs."""

from app.chip_offer import should_offer_chip


class TestChipStrayField:
    def test_inturristo_offers_for_ru(self):
        assert should_offer_chip("Inturristo", target_lang="ru") is True

    def test_cinturristo_offers_after_peel(self):
        # Was skipped as camelCase before peel — H3
        assert should_offer_chip("cInturristo", target_lang="ru") is True

    def test_lone_c_no_chip(self):
        assert should_offer_chip("c", target_lang="ru") is False
        assert should_offer_chip("с", target_lang="ru") is False

    def test_english_phrase(self):
        assert should_offer_chip("Russo Inturristo", target_lang="ru") is True
