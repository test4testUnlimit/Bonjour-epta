"""Numbered chivoblya chip styles — user picks.

Style 1 (default, Lebedev dual-action pill):
  [ 1/3 👁 ] | [ 2/3  chivoblya? ]
  eye  → start translate, then mini popup card
  text → open main window (no other changes)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChipStyle:
    id: int
    name: str
    note: str
    bg: str
    bg_hover: str
    border: str
    ink: str
    # dual: left third = eye→popup, right two-thirds = chivoblya→main
    dual_action: bool
    icon: str
    radius_look: str


STYLES: list[ChipStyle] = [
    ChipStyle(
        id=1,
        name="Dual 1/3 · 2/3",
        note="глаз → попап с переводом · чивобля? → главное окно",
        bg="#f1f3f4",
        bg_hover="#e8eaed",
        border="#dadce0",
        ink="#3c4043",
        dual_action=True,
        icon="👁",
        radius_look="pill",
    ),
    ChipStyle(
        id=2,
        name="Chrome soft",
        note="одна пилюля → попап (как глаз)",
        bg="#f1f3f4",
        bg_hover="#e8eaed",
        border="#dadce0",
        ink="#3c4043",
        dual_action=False,
        icon="",
        radius_look="pill",
    ),
    ChipStyle(
        id=3,
        name="White paper",
        note="белая пилюля → попап",
        bg="#ffffff",
        bg_hover="#f8f9fa",
        border="#dadce0",
        ink="#202124",
        dual_action=False,
        icon="",
        radius_look="pill",
    ),
    ChipStyle(
        id=4,
        name="Outline ghost",
        note="контур → попап",
        bg="#f8f9fa",
        bg_hover="#e8eaed",
        border="#9aa0a6",
        ink="#3c4043",
        dual_action=False,
        icon="",
        radius_look="pill",
    ),
    ChipStyle(
        id=5,
        name="Dual white",
        note="как №1, белый фон",
        bg="#ffffff",
        bg_hover="#f1f3f4",
        border="#dadce0",
        ink="#3c4043",
        dual_action=True,
        icon="👁",
        radius_look="pill",
    ),
    ChipStyle(
        id=6,
        name="Ink bold",
        note="жирнее текст → попап",
        bg="#ffffff",
        bg_hover="#f1f3f4",
        border="#bdc1c6",
        ink="#000000",
        dual_action=False,
        icon="",
        radius_look="pill",
    ),
]

_BY_ID = {s.id: s for s in STYLES}
DEFAULT_STYLE_ID = 1


def get_style(style_id: int | None) -> ChipStyle:
    if style_id is None:
        return _BY_ID[DEFAULT_STYLE_ID]
    return _BY_ID.get(int(style_id), _BY_ID[DEFAULT_STYLE_ID])
