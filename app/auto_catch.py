"""Auto-catch field bugs without waiting for the tray's report-a-bug item.

From 2026-08-09 BUGMARKs we know two signatures that are safe to stamp:

  * empty capture after a successful-looking Ctrl+C inject
    (clipboard untouched) — the "no chip" bug
  * selection that is just a lone c (latin or U+0441), or a word clearly prefixed
    by a stray c (cInturristo) — the "stray c" bug

Throttled so a sticky Firefox/ShareX race does not flood bugs/.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any

from . import bug_report, logutil, peers

KIND_AUTO_EMPTY = "auto_empty_capture"
KIND_AUTO_STRAY_C = "auto_stray_c"
KIND_AUTO_SKIP = "auto_chip_skip_mangled"

# register labels on the bug_report side
bug_report.KIND_LABELS[KIND_AUTO_EMPTY] = "авто: пустой захват (нет чипа)"
bug_report.KIND_LABELS[KIND_AUTO_STRAY_C] = "авто: лишняя c/с"
bug_report.KIND_LABELS[KIND_AUTO_SKIP] = "авто: чип срезан после порчи c…"

_THROTTLE_S = 12.0
_MAX_PER_HOUR = 30
_lock = threading.Lock()
_last_by_kind: dict[str, float] = {}
_hour_stamp = 0.0
_hour_count = 0

# lone c / Cyrillic es (same physical key)
_RE_LONE_C = re.compile(r"^[cсCС]$")
# leading latin/cyrillic c glued to a Capitalized rest (cInturristo)
_RE_STRAY_PREFIX = re.compile(r"^[cсCС]([A-ZА-ЯЁ][\w'’-]*)$")


def looks_stray_c(text: str | None) -> str | None:
    """Return a short reason if `text` looks like the leaked-C bug, else None."""
    t = (text or "").strip()
    if not t:
        return None
    if _RE_LONE_C.match(t):
        return "lone_c"
    m = _RE_STRAY_PREFIX.match(t)
    if m and len(m.group(1)) >= 4:
        return f"prefix_c+{m.group(1)[:40]}"
    return None


def note_empty_capture(
    *,
    polls: int = 0,
    previous_head: str = "",
    app: Any | None = None,
) -> None:
    """Ctrl+C claimed ok but clipboard never changed → no chip."""
    peers_s = peers.summary()
    note = (
        f"clipboard untouched after inject polls={polls} "
        f"prev_head={logutil.head(previous_head, 80)!r} peers={peers_s}"
    )
    _emit(KIND_AUTO_EMPTY, note, app=app)


def note_stray_selection(text: str, *, reason: str, app: Any | None = None) -> None:
    note = f"reason={reason} text={text[:120]!r} peers={peers.summary()}"
    _emit(KIND_AUTO_STRAY_C, note, app=app)


def note_chip_skip_mangled(text: str, *, app: Any | None = None) -> None:
    reason = looks_stray_c(text)
    if not reason:
        return
    note = f"chip skipped on mangled selection reason={reason} text={text[:120]!r}"
    _emit(KIND_AUTO_SKIP, note, app=app)


def _emit(kind: str, note: str, *, app: Any | None) -> None:
    now = time.perf_counter()
    with _lock:
        global _hour_stamp, _hour_count
        if now - _hour_stamp > 3600.0:
            _hour_stamp = now
            _hour_count = 0
        if _hour_count >= _MAX_PER_HOUR:
            logutil.get().debug("auto_catch drop (hour cap) kind=%s", kind)
            return
        last = _last_by_kind.get(kind, 0.0)
        if now - last < _THROTTLE_S:
            logutil.get().debug("auto_catch throttle kind=%s", kind)
            return
        _last_by_kind[kind] = now
        _hour_count += 1

    logutil.get().warning("AUTO_CATCH kind=%s %s", kind, note[:300])

    def _write() -> None:
        try:
            bug_report.report(kind, note, app=app, auto=True)
        except Exception:  # noqa: BLE001
            logutil.exc("auto_catch report")

    # Never block the capture / UI thread on JSON+log I/O
    threading.Thread(target=_write, daemon=True, name="bonjur-auto-catch").start()
