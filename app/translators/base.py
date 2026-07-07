"""Translator provider contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(slots=True)
class ExampleItem:
    """One alternative / synonym chip (Google-style under the pane)."""

    word: str
    pos: str = ""  # part of speech / group label
    meanings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TranslateResult:
    text: str
    detected_source: str | None = None
    provider: str = ""
    error: str | None = None
    # Google-style extras (when engine provides them)
    alternatives: list[str] = field(default_factory=list)
    examples: list[ExampleItem] = field(default_factory=list)
    translit: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.text)


class Translator(ABC):
    id: str
    label: str
    needs_api_key: bool = False
    supports_auto: bool = True

    @abstractmethod
    def translate(
        self,
        text: str,
        source: str = "auto",
        target: str = "ru",
        api_key: str | None = None,
    ) -> TranslateResult:
        raise NotImplementedError
