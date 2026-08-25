"""Offline acronym decoding for the main window.

    from app import acronyms
    acronyms.quick_scan("Send the PPAP by EOW")   # → 2
    acronyms.explain(text).hits                   # → ranked meanings

Packs live in app/acronyms/data (public, in git) and ~/.bonjur-epta/packs
(site-specific, never committed). Nothing here touches the network or Tk.
"""

from __future__ import annotations

from .resolve import Hit, Report, explain, quick_scan
from .store import (
    Entry,
    Index,
    Pack,
    index,
    is_enabled,
    local_dir,
    packs,
    reload,
    set_enabled,
    warm,
)

__all__ = [
    "Entry",
    "Hit",
    "Index",
    "Pack",
    "Report",
    "explain",
    "index",
    "is_enabled",
    "local_dir",
    "packs",
    "quick_scan",
    "reload",
    "set_enabled",
    "warm",
]
