"""Watch mouse drag / double-click → capture selection → show «чивобля?»."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable

from . import logutil
from .selection import get_selected_text

try:
    import mouse
except ImportError:  # pragma: no cover
    mouse = None  # type: ignore

# drag threshold in px — below this may still be double-click word select
DRAG_PX = 6
DOUBLE_CLICK_MS = 420
MIN_CHARS = 1
MAX_CHARS = 8000
# ignore identical selection re-pops for a short window
DEDUP_MS = 900
# settle after mouse-up before Ctrl+C (browsers need a longer tick to finalize selection)
SETTLE_S = 0.12


class SelectionWatcher:
    def __init__(
        self,
        on_selection: Callable[[str, int, int], None],
        *,
        should_ignore: Callable[[int, int], bool] | None = None,
    ) -> None:
        """
        on_selection(text, screen_x, screen_y)
        should_ignore(x, y) → True if cursor is over our own UI (skip capture)
        """
        self.on_selection = on_selection
        self.should_ignore = should_ignore or (lambda _x, _y: False)
        self._down_pos: tuple[int, int] | None = None
        self._down_ts = 0.0
        self._last_up_ts = 0.0
        self._last_up_pos: tuple[int, int] | None = None
        self._last_text = ""
        self._last_fire_ts = 0.0
        self._busy = False
        self._enabled = True
        self._handlers: list = []

    def start(self) -> None:
        if mouse is None:
            raise RuntimeError("package 'mouse' is not installed")
        if self._handlers:
            return

        def on_down() -> None:
            if not self._enabled:
                return
            try:
                self._down_pos = mouse.get_position()
            except Exception:  # noqa: BLE001
                self._down_pos = None
            self._down_ts = time.perf_counter()

        def on_up() -> None:
            if not self._enabled or self._busy:
                return
            try:
                pos = mouse.get_position()
            except Exception:  # noqa: BLE001
                return
            now = time.perf_counter()
            down = self._down_pos
            self._down_pos = None

            # skip clicks on our chip / main window
            if self.should_ignore(pos[0], pos[1]):
                self._last_up_ts = now
                self._last_up_pos = pos
                return

            dragged = False
            if down is not None:
                dragged = _dist(down, pos) >= DRAG_PX

            # double-click word/line select: two ups close in time & space, little/no drag
            is_double = False
            if self._last_up_pos is not None:
                dt_ms = (now - self._last_up_ts) * 1000.0
                if dt_ms <= DOUBLE_CLICK_MS and _dist(self._last_up_pos, pos) <= DRAG_PX:
                    is_double = True

            self._last_up_ts = now
            self._last_up_pos = pos

            if not dragged and not is_double:
                return

            # capture off UI/hook thread
            threading.Thread(
                target=self._capture_and_fire,
                args=(pos[0], pos[1]),
                daemon=True,
            ).start()

        # mouse library registers global hooks
        self._handlers.append(mouse.on_button(on_down, buttons=("left",), types=("down",)))
        self._handlers.append(mouse.on_button(on_up, buttons=("left",), types=("up",)))

    def stop(self) -> None:
        self._enabled = False
        if mouse is None:
            return
        for h in self._handlers:
            try:
                mouse.unhook(h)
            except Exception:  # noqa: BLE001
                pass
        self._handlers.clear()

    def pause(self) -> None:
        self._enabled = False

    def resume(self) -> None:
        self._enabled = True

    def _capture_and_fire(self, x: int, y: int) -> None:
        if self._busy:
            return
        self._busy = True
        # prevent re-entry while we synthesize Ctrl+C
        was_enabled = self._enabled
        self._enabled = False
        try:
            time.sleep(SETTLE_S)
            # no clipboard_fallback: chip must show *selection*, not stale clipboard
            try:
                # Crow-style grab for chip cache (mods usually already up after mouse-up)
                text = get_selected_text(
                    restore_clipboard=True,
                    settle_s=0.6,
                    clipboard_fallback=False,
                )
            except Exception:  # noqa: BLE001 — never kill watcher thread
                logutil.exc("watcher get_selected_text")
                return
            text = (text or "").strip()
            if not text or len(text) < MIN_CHARS or len(text) > MAX_CHARS:
                logutil.get().debug("watcher skip empty/short/long len=%s", len(text or ""))
                return
            now = time.perf_counter()
            if text == self._last_text and (now - self._last_fire_ts) * 1000 < DEDUP_MS:
                logutil.get().debug("watcher dedup")
                return
            self._last_text = text
            self._last_fire_ts = now
            logutil.get().info("watcher fire len=%s at=%s,%s", len(text), x, y)
            try:
                self.on_selection(text, x, y)
            except Exception:  # noqa: BLE001
                logutil.exc("watcher on_selection")
        finally:
            self._busy = False
            self._enabled = was_enabled


def _dist(a: tuple[int, int], b: tuple[int, int]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
