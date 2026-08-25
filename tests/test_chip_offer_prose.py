"""Ordinary English prose must reach the chip; real code must not.

The old _RE_CODE was compiled (?is), so "Let me know", "the function of the
liver" and "Select your organization from the list" all matched a code keyword
and the chip was silently dropped. That was the single biggest cause of
"selected something, no chip".
"""

from app import chip_offer
from app.chip_offer import should_offer_chip

PROSE = [
    "Let me know if that works",
    "We should ship this on Friday and let the team know",
    "Scope: Select your organization from the list",
    "Please select a file from the folder",
    "The class was cancelled",
    "a class of problems nobody solved",
    "the function of the liver",
    "import duties on steel were raised",
    "The newest one is going to be the mirrors.",
]

CODE = [
    "let x = 5;",
    "var i=0",
    "const a = 1",
    "def foo(x):",
    "class Foo(Base):",
    "function init() {",
    "SELECT id FROM users WHERE a=1",
    "import os",
    "import numpy as np",
    "from app import chip_offer",
    "git commit -m x",
    "npm install",
    '{"a": 1}',
    '<div class="x">',
    r"C:\Projects\x.py",
]


class TestProseIsNotCode:
    def test_prose_gets_a_chip(self):
        assert [t for t in PROSE if not should_offer_chip(t, target_lang="ru")] == []

    def test_code_still_dropped(self):
        assert [t for t in CODE if should_offer_chip(t, target_lang="ru")] == []


class TestSkipReason:
    def test_reason_names_the_filter_that_fired(self):
        should_offer_chip("def foo(x):", target_lang="ru")
        assert chip_offer.last_skip_reason == "code_or_junk"

    def test_target_script_is_not_blamed_for_a_code_drop(self):
        should_offer_chip("Привет как дела", target_lang="ru")
        assert chip_offer.last_skip_reason == "already_target_script"

    def test_reason_cleared_when_the_chip_is_offered(self):
        assert should_offer_chip("Let me know if that works", target_lang="ru")
        assert chip_offer.last_skip_reason == ""
