"""Online enrichment — deliberately empty for now.

Decided during planning: ship the curated core first, judge it on real texts,
then decide whether to pull NIST e-Handbook (public domain), JCGM 200 / VIM
(CC BY-ND — link only, no derivative text) or ru.wikipedia.

The seam exists so resolve.py never has to be rewritten for it: an online
result should arrive as a normal store.Entry with its own pack id.
"""

from __future__ import annotations

from .store import Entry

ENABLED = False


def lookup(term: str) -> list[Entry]:  # noqa: ARG001
    """Future: fetch a meaning for an unknown acronym. Today: nothing."""
    return []
