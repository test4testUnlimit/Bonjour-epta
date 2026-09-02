"""Watch mouse drag / double-click -> capture selection -> show chip."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable

from . import input_arbiter, logutil
from .selection import get_selected_text, sanitize_selection

try:
    import mouse
except ImportError:  # pragma: no cover
    mouse = None  # type: ignore

DRAG_PX = 6
DOUBLE_CLICK_MS = 420
MIN_CHARS = 1
MAX_CHARS = 8000
DEDUP_MS = 900
SETTLE_S = 0.08  # was 0.18 — RTL / end-of-line selections clear faster in Firefox


class SelectionWatcher:
    def __init__(
        self,
        on_selection: Callable[[str, int, int], None],
        *,
        should_ignore: Callable[[int, int], bool] | None = None,
    ) -> None:
        self.on_selection = on_selection
        self.should_ignore = should_ignore or (lambda _x, _y: False)
        self._down_pos: tuple[int, int] | None = None
        self._down_ts = 0.0
        self._last_up_ts = 0.0
        self._last_up_pos: tuple[int, int] | None = None
        self._last_text = ""
        self._last_fire_ts = 0.0
        self._busy = False
        self._cap_lock = threading.Lock()
        self._enabled = True
        self._handlers: list = []

    def start(self) -> None:
        if mouse is None:
            raise RuntimeError("package 'mouse' is not installed")
        if self._handlers:
            return

        def on_down() -> None:
            # Deliberately NOT gated on _enabled. A hotkey pauses the watcher
            # for 0.4-5.4 s; a drag that starts inside that window used to
            # lose its down position and then look like a bare click on
            # mouse-up, so the whole selection vanished with no log line.
            # Recording a coordinate is free — on_up still decides.
            try:
                self._down_pos = mouse.get_position()
            except Exception:
                self._down_pos = None
            self._down_ts = time.perf_counter()

            # Chromium keeps its a11y tree off until a UIA client asks; the
            # first ask returns empty immediately and only *then* wakes the
            # renderer. Asking at mouse-DOWN spends the whole drag warming
            # it, so the read at mouse-UP finds a tree that already exists.
            # ponytail: one probe per left-click. If a huge page makes
            # a11y-enable hitch the drag, gate it on "last probe missed".
            if not input_arbiter.busy():
                try:
                    from . import silent_selection

                    silent_selection.warm()
                except Exception:  # noqa: BLE001
                    pass

        def on_up() -> None:
            if not self._enabled:
                return
            try:
                pos = mouse.get_position()
            except Exception:
                return
            now = time.perf_counter()
            down = self._down_pos
            self._down_pos = None

            if self.should_ignore(pos[0], pos[1]):
                self._last_up_ts = now
                self._last_up_pos = pos
                return

            dragged = False
            if down is not None:
                dragged = _dist(down, pos) >= DRAG_PX

            is_double = False
            if self._last_up_pos is not None:
                dt_ms = (now - self._last_up_ts) * 1000.0
                if dt_ms <= DOUBLE_CLICK_MS and _dist(self._last_up_pos, pos) <= DRAG_PX:
                    is_double = True

            self._last_up_ts = now
            self._last_up_pos = pos

            # Busy is checked here, AFTER the up history is written. Bailing
            # earlier froze _last_up_pos at the previous word, so the click
            # that completed a double-click was measured against the wrong
            # position and the gesture after a capture was silently lost.
            if self._busy:
                logutil.get().info("watcher drop -- capture busy")
                return

            if not dragged and not is_double:
                return

            # Dragging over a lock screen must produce nothing at all: no
            # capture thread, no Ctrl+C, no clipboard read. The check is here
            # rather than deeper down so we do not even take the clip lock.
            if input_arbiter.busy():
                logutil.get().debug("watcher skip -- input held by another app")
                return

            kind = "double" if is_double else "drag"
            drag_dx = 0
            drag_dy = 0
            if down is not None:
                drag_dx = int(pos[0] - down[0])
                drag_dy = int(pos[1] - down[1])
            # Chip at mouse-UP — where the selection ended / cursor released.
            chip_x = int(pos[0])
            chip_y = int(pos[1])
            logutil.get().info(
                "watcher click kind=%s at=%s,%s drag_dx=%s drag_dy=%s",
                kind,
                chip_x,
                chip_y,
                drag_dx,
                drag_dy,
            )

            threading.Thread(
                target=self._capture_and_fire,
                args=(chip_x, chip_y, now),
                daemon=True,
            ).start()

        self._handlers.append(mouse.on_button(on_down, buttons=("left",), types=("down",)))
        self._handlers.append(mouse.on_button(on_up, buttons=("left",), types=("up",)))

    def stop(self) -> None:
        self._enabled = False
        if mouse is None:
            return
        for h in self._handlers:
            try:
                mouse.unhook(h)
            except Exception:
                pass
        self._handlers.clear()

    def pause(self) -> None:
        self._enabled = False

    def resume(self) -> None:
        self._enabled = True

    def _capture_and_fire(self, x: int, y: int, since: float | None = None) -> None:
        if not self._cap_lock.acquire(blocking=False):
            logutil.get().debug("watcher skip -- capture already running")
            return
        # FIX bug #2: Don't touch self._enabled here.
        # Old code saved/restored _enabled, which overwrote pause() calls
        # made by on_hotkey_fire during the capture window (1-5s).
        # _busy already blocks re-entry via on_up check.
        self._busy = True
        try:
            time.sleep(SETTLE_S)

            # If paused during settle (e.g. hotkey fired), bail out.
            if not self._enabled:
                logutil.get().debug("watcher skip -- paused during settle")
                return

            # Right-to-left / end-to-start drags settle the selection a beat
            # later than left-to-right ones (Firefox especially: the anchor
            # flips only after mouse-up). One fixed SETTLE_S is too early for
            # them, so an empty first read retries a few times before we give
            # up on the chip. Cheap: each retry is a silent read, no inject.
            text = ""
            for attempt, wait in enumerate((0.0, 0.12, 0.2, 0.3)):
                if wait:
                    time.sleep(wait)
                    if not self._enabled:
                        break
                try:
                    # NEVER inject from the chip path. Fake Ctrl+C on every
                    # drag raced ShareX/Caramba/AHK and the user's own copy.
                    # No settle_s: allow_inject=False returns before it is read
                    # (selection.py:533), so passing one only implied a budget
                    # this path never had.
                    text = get_selected_text(
                        restore_clipboard=True,
                        clipboard_fallback=False,
                        # mouse-up stamp: a Ctrl+C after it is the user copying
                        # what they just selected, not a stale clipboard
                        since=since,
                        allow_inject=False,
                    )
                except Exception:
                    logutil.exc("watcher get_selected_text")
                    return
                text = sanitize_selection(text)
                if text:
                    if attempt:
                        logutil.get().info("watcher capture ok on retry %s len=%s", attempt, len(text))
                    break
            if not text or len(text) < MIN_CHARS or len(text) > MAX_CHARS:
                logutil.get().info(
                    "watcher empty capture len=%s — no chip (silent miss, no inject)",
                    len(text or ""),
                )
                try:
                    from . import peers

                    peers.log_snapshot("watcher empty peers")
                except Exception:  # noqa: BLE001
                    pass
                return

            # Re-check after long capture -- pause() may have been called.
            if not self._enabled:
                logutil.get().debug("watcher skip -- paused after capture")
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
            except Exception:
                logutil.exc("watcher on_selection")
        finally:
            self._busy = False
            self._cap_lock.release()


def _dist(a: tuple[int, int], b: tuple[int, int]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])