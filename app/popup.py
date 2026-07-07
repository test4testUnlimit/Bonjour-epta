"""Google-style «чивобля?» pill + mini translation card near selection.

Stable: long lifetime on card, no accidental hide, safe UI updates from threads.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections.abc import Callable

import pyperclip

from . import dpi
from . import logutil
from . import settings as cfg
from . import translators as tr
from .chip_styles import get_style
from .screen import clamp_popup

# default sizes; split chips a bit wider
CHIP_W, CHIP_H = 120, 36
CHIP_W_SPLIT = 148

CARD_W = 360
CARD_MIN_H = 140
CARD_MAX_H = 360
CARD_BG = "#ffffff"
CARD_BORDER = "#dadce0"
CARD_INK = "#202124"
CARD_MUTED = "#5f6368"
CARD_FOOT = "#f8f9fa"
ERR = "#c5221f"


class ChivoblyaPopup:
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_open_main: Callable[[str], None] | None = None,
        on_visibility: Callable[[bool], None] | None = None,
    ) -> None:
        self._master = master
        self._on_open_main = on_open_main
        self._on_visibility = on_visibility
        self._text = ""
        self._translation = ""
        self._anchor = (0, 0)
        self._mode = "chip"

        self._win: tk.Toplevel | None = None
        self._chip_frame: tk.Frame | None = None
        self._card_frame: tk.Frame | None = None
        self._src_lbl: tk.Label | None = None
        self._tgt_lbl: tk.Label | None = None
        self._status_lbl: tk.Label | None = None

        self._hide_after_id: str | None = None
        self._visible = False
        self._click_guard = False
        self._job = 0
        self._cur_w = CHIP_W
        self._cur_h = CHIP_H
        self._alive = True
        # thread-safe UI: worker never calls Tk directly
        self._ui_q: queue.SimpleQueue = queue.SimpleQueue()
        self._pump_on = False

    @property
    def visible(self) -> bool:
        return self._visible

    @property
    def mode(self) -> str:
        return self._mode

    def show(self, text: str, x: int, y: int, auto_hide_ms: int = 12000) -> None:
        if not self._alive:
            return
        log = logutil.get()
        text = (text or "").strip()
        if not text:
            return
        # don't reset an open card with a new chip flash
        if self._visible and self._mode == "card":
            log.debug("ignore new chip while card open")
            return

        self._text = text
        self._translation = ""
        self._anchor = (int(x), int(y))
        self._mode = "chip"
        self._job += 1
        try:
            self._ensure_win()
            self._rebuild_chip()
            self._show_chip_ui()
            self._place(self._cur_w, self._cur_h, x, y)
            self._map_window()
            self._set_visible(True)
            self._arm_hide(auto_hide_ms)
            log.info(
                "chip show len=%s at=(%s,%s) head=%r",
                len(text),
                x,
                y,
                text[:50],
            )
        except Exception:  # noqa: BLE001
            logutil.exc("popup.show")

    def hide(self) -> None:
        logutil.get().debug("popup.hide mode=%s", self._mode)
        self._cancel_hide()
        self._set_visible(False)
        self._mode = "chip"
        if self._win is not None:
            try:
                self._win.withdraw()
            except Exception:  # noqa: BLE001
                pass

    def destroy(self) -> None:
        self._alive = False
        self.hide()
        if self._win is not None:
            try:
                self._win.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._win = None

    def contains_screen_point(self, x: int, y: int) -> bool:
        if not self._visible or self._win is None:
            return False
        try:
            pad = 12
            wx = self._win.winfo_rootx() - pad
            wy = self._win.winfo_rooty() - pad
            return (
                wx <= x <= wx + self._cur_w + 2 * pad
                and wy <= y <= wy + self._cur_h + 2 * pad
            )
        except Exception:  # noqa: BLE001
            return False

    # ── build ───────────────────────────────────────────────
    def _ensure_win(self) -> None:
        if self._win is not None:
            return
        win = tk.Toplevel(self._master)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#dadce0")
        win.withdraw()
        # don't destroy app if this window errors
        win.protocol("WM_DELETE_WINDOW", self.hide)

        chip_outer = tk.Frame(win, bg="#dadce0")
        self._chip_host = chip_outer  # rebuilt per style on show
        self._rebuild_chip()

        # CARD
        card_outer = tk.Frame(win, bg=CARD_BORDER)
        body = tk.Frame(card_outer, bg=CARD_BG)
        body.pack(fill="both", expand=True, padx=1, pady=1)

        head = tk.Frame(body, bg=CARD_BG)
        head.pack(fill="x", padx=14, pady=(12, 4))
        # language only, e.g. (английский) — not the word «перевод»
        lang_lbl = tk.Label(
            head, text="", font=("Segoe UI", 9), fg=CARD_MUTED, bg=CARD_BG, anchor="w"
        )
        lang_lbl.pack(side="left")
        close = tk.Label(
            head, text="✕", font=("Segoe UI", 10), fg=CARD_MUTED, bg=CARD_BG, cursor="hand2"
        )
        close.pack(side="right")
        close.bind("<ButtonRelease-1>", lambda _e: self.hide())

        # only the translation — no source repeat; Georgia for Lebedev-readable body
        tgt = tk.Label(
            body,
            text="",
            font=("Georgia", 14),
            fg=CARD_INK,
            bg=CARD_BG,
            wraplength=CARD_W - 32,
            justify="left",
            anchor="nw",
        )
        tgt.pack(fill="both", expand=True, padx=14, pady=(4, 8))

        status = tk.Label(
            body, text="", font=("Segoe UI", 8), fg=CARD_MUTED, bg=CARD_BG, anchor="w"
        )
        status.pack(fill="x", padx=14, pady=(0, 4))

        foot = tk.Frame(body, bg=CARD_FOOT)
        foot.pack(fill="x", side="bottom")
        actions = tk.Frame(foot, bg=CARD_FOOT)
        actions.pack(padx=12, pady=10, anchor="w")

        self._make_pill(actions, "⎘  копировать", self._copy_tr).pack(side="left", padx=(0, 8))
        self._make_pill(actions, "↗  в окно", self._open_main).pack(side="left")

        self._win = win
        self._chip_frame = chip_outer
        self._card_frame = card_outer
        self._lang_lbl = lang_lbl
        self._src_lbl = None  # source text intentionally not shown
        self._tgt_lbl = tgt
        self._status_lbl = status

    def _rebuild_chip(self) -> None:
        """Style from picker. Dual pill: 1/3 eye→popup+translate, 2/3 chivoblya→main."""
        host = getattr(self, "_chip_host", None)
        if host is None:
            return
        for ch in host.winfo_children():
            ch.destroy()
        st = get_style(cfg.get().chip_style_id)
        host.configure(bg=st.border)
        self._chip_style = st
        self._cur_h = CHIP_H

        def zone_hover(widgets: list, base: str, hover: str):
            def on(_e=None) -> None:
                for w in widgets:
                    try:
                        w.configure(bg=hover)
                    except Exception:  # noqa: BLE001
                        pass

            def off(_e=None) -> None:
                for w in widgets:
                    try:
                        w.configure(bg=base)
                    except Exception:  # noqa: BLE001
                        pass

            for w in widgets:
                w.bind("<Enter>", on)
                w.bind("<Leave>", off)

        def bind_click(widgets: list, fn) -> None:
            for w in widgets:
                w.bind("<ButtonRelease-1>", lambda _e, f=fn: f())

        if st.dual_action:
            # ── 1/3 eye | 2/3 «чивобля?» ──
            self._cur_w = 156
            # fixed width left third
            left = tk.Frame(host, bg=st.bg, cursor="hand2", width=48)
            left.pack(side="left", fill="y", padx=(1, 0), pady=1)
            left.pack_propagate(False)
            ic = tk.Label(
                left,
                text=st.icon or "👁",
                font=("Segoe UI Emoji", 12),
                fg=st.ink,
                bg=st.bg,
                cursor="hand2",
            )
            ic.place(relx=0.5, rely=0.5, anchor="center")

            tk.Frame(host, bg=st.border, width=1).pack(side="left", fill="y", pady=1)

            right = tk.Frame(host, bg=st.bg, cursor="hand2")
            right.pack(side="left", fill="both", expand=True, padx=(0, 1), pady=1)
            lb = tk.Label(
                right,
                text="чивобля?",
                font=("Segoe UI", 10),
                fg=st.ink,
                bg=st.bg,
                cursor="hand2",
            )
            lb.place(relx=0.5, rely=0.5, anchor="center")

            left_ws = [left, ic]
            right_ws = [right, lb]
            zone_hover(left_ws, st.bg, st.bg_hover)
            zone_hover(right_ws, st.bg, st.bg_hover)
            # eye: translate → mini card
            bind_click(left_ws, self._on_eye_click)
            # label: main window, no other changes
            bind_click(right_ws, self._on_chivoblya_main_click)
        else:
            # whole pill → mini popup (same as eye)
            self._cur_w = CHIP_W
            inner = tk.Frame(host, bg=st.bg, cursor="hand2")
            inner.pack(fill="both", expand=True, padx=1, pady=1)
            lb = tk.Label(
                inner,
                text="чивобля?",
                font=("Segoe UI", 10),
                fg=st.ink,
                bg=st.bg,
                padx=14,
                pady=8,
                cursor="hand2",
            )
            lb.pack(expand=True)
            ws = [inner, lb]
            zone_hover(ws, st.bg, st.bg_hover)
            bind_click(ws, self._on_eye_click)
    def apply_style_now(self) -> None:
        if self._win is None:
            return
        try:
            self._rebuild_chip()
            if self._visible and self._mode == "chip":
                self._place(self._cur_w, self._cur_h, *self._anchor)
                self._map_window()
        except Exception:  # noqa: BLE001
            logutil.exc("apply_style_now")

    def _make_pill(self, parent: tk.Frame, text: str, cmd: Callable) -> tk.Frame:
        # fixed Google soft tokens for card foot (not chip style)
        border, bg, hover, ink = "#dadce0", "#f1f3f4", "#e8eaed", "#3c4043"
        outer = tk.Frame(parent, bg=border, cursor="hand2")
        lab = tk.Label(
            outer,
            text=text,
            font=("Segoe UI", 9),
            fg=ink,
            bg=bg,
            padx=12,
            pady=5,
            cursor="hand2",
        )
        lab.pack(padx=1, pady=1)

        def run(_e=None) -> None:
            try:
                cmd()
            except Exception:  # noqa: BLE001
                logutil.exc("pill action")

        def on(_e=None) -> None:
            lab.configure(bg=hover)

        def off(_e=None) -> None:
            lab.configure(bg=bg)

        for w in (outer, lab):
            w.bind("<ButtonRelease-1>", run)
            w.bind("<Enter>", on)
            w.bind("<Leave>", off)
        return outer

    def _show_chip_ui(self) -> None:
        assert self._chip_frame and self._card_frame
        try:
            self._card_frame.pack_forget()
        except Exception:  # noqa: BLE001
            pass
        self._chip_frame.pack(fill="both", expand=True)
        self._mode = "chip"
        # width already set by _rebuild_chip
        self._cur_h = CHIP_H
    def _show_card_ui(self) -> None:
        assert self._chip_frame and self._card_frame
        try:
            self._chip_frame.pack_forget()
        except Exception:  # noqa: BLE001
            pass
        self._card_frame.pack(fill="both", expand=True)
        self._mode = "card"
        # no source echo — only loading translation
        if self._tgt_lbl:
            self._tgt_lbl.configure(text="…", fg=CARD_MUTED, font=("Georgia", 14))
        if getattr(self, "_lang_lbl", None):
            self._lang_lbl.configure(text="(…)")
        if self._status_lbl:
            self._status_lbl.configure(text="")
        self._cur_w = CARD_W
        self._cur_h = CARD_MIN_H + 20
        self._place(self._cur_w, self._cur_h, *self._anchor)
        self._map_window()

    # ── click / translate ───────────────────────────────────
    def _on_eye_click(self) -> None:
        """1/3 eye: kick off translate first, then show mini popup card."""
        if not self._alive or self._click_guard:
            return
        if not self._visible or self._mode != "chip":
            return
        self._click_guard = True
        text = self._text
        log = logutil.get()
        log.info("EYE click → translate then mini card len=%s", len(text))
        try:
            # 1) start network translate immediately
            self._start_translate(text)
            # 2) show card (loading state) right after request is in flight
            self._show_card_ui()
            self._arm_hide(45000)
        except Exception:  # noqa: BLE001
            logutil.exc("eye → card")
        finally:
            try:
                self._master.after(350, self._clear_guard)
            except Exception:  # noqa: BLE001
                self._click_guard = False

    def _on_chivoblya_main_click(self) -> None:
        """2/3 «чивобля?»: open main window only — no mini card."""
        if not self._alive or self._click_guard:
            return
        if not self._visible or self._mode != "chip":
            return
        self._click_guard = True
        text = self._text
        logutil.get().info("CHIVOBLYA click → main window len=%s", len(text))
        try:
            self.hide()
            if text and self._on_open_main:
                self._on_open_main(text)
        except Exception:  # noqa: BLE001
            logutil.exc("chivoblya → main")
        finally:
            try:
                self._master.after(350, self._clear_guard)
            except Exception:  # noqa: BLE001
                self._click_guard = False

    def _clear_guard(self) -> None:
        self._click_guard = False

    def _start_translate(self, text: str) -> None:
        """Fire translate ASAP; result applied when card is ready (or queued)."""
        job = self._job
        s = cfg.get()
        source = s.source_lang or "auto"
        target = s.target_lang or "ru"
        provider = s.provider_id
        logutil.get().info(
            "mini translate start job=%s provider=%s %s→%s",
            job,
            provider,
            source,
            target,
        )

        def work() -> None:
            try:
                result = tr.translate(
                    text, source=source, target=target, provider_id=provider
                )
            except Exception as exc:  # noqa: BLE001
                logutil.exc("mini translate thread")
                result = tr.TranslateResult(text="", provider=provider or "", error=str(exc))
            if not self._alive:
                return
            self._ui_q.put(lambda r=result, j=job: self._apply_tr(j, r))

        self._ensure_pump()
        threading.Thread(target=work, daemon=True).start()
    def _ensure_pump(self) -> None:
        if self._pump_on or not self._alive:
            return
        self._pump_on = True

        def pump() -> None:
            if not self._alive:
                self._pump_on = False
                return
            try:
                while True:
                    fn = self._ui_q.get_nowait()
                    try:
                        fn()
                    except Exception:  # noqa: BLE001
                        logutil.exc("ui pump job")
            except queue.Empty:
                pass
            try:
                self._master.after(40, pump)
            except Exception:  # noqa: BLE001
                self._pump_on = False

        try:
            self._master.after(40, pump)
        except Exception:  # noqa: BLE001
            self._pump_on = False
            logutil.exc("start ui pump")

    def _apply_tr(self, job: int, result: tr.TranslateResult) -> None:
        if not self._alive or job != self._job:
            return
        if not self._visible or self._mode != "card":
            return
        log = logutil.get()
        try:
            from .languages import short_ru

            if not result.ok:
                self._translation = ""
                if self._tgt_lbl:
                    self._tgt_lbl.configure(text="не удалось перевести", fg=ERR)
                if self._status_lbl:
                    self._status_lbl.configure(text=(result.error or "ошибка")[:70])
                log.warning("mini tr fail: %s", result.error)
                self._arm_hide(15000)
                return

            self._translation = result.text or ""
            # header: (английский) from detected source, not «перевод»
            src_code = result.detected_source or cfg.get().source_lang or "auto"
            if getattr(self, "_lang_lbl", None):
                self._lang_lbl.configure(text=f"({short_ru(src_code)})")
            if self._tgt_lbl:
                # only translation, Georgia — no source repeat
                self._tgt_lbl.configure(
                    text=self._translation, fg=CARD_INK, font=("Georgia", 15)
                )
            if self._status_lbl:
                self._status_lbl.configure(text="")

            # grow card for text
            lines = max(2, min(14, 1 + len(self._translation) // 32))
            h = 120 + lines * 18
            self._cur_h = max(CARD_MIN_H, min(h, CARD_MAX_H))
            self._place(self._cur_w, self._cur_h, *self._anchor)
            self._map_window()
            # refresh lifetime after success
            self._arm_hide(45000)
            log.info("mini tr ok len=%s head=%r", len(self._translation), self._translation[:60])
        except Exception:  # noqa: BLE001
            logutil.exc("apply_tr UI")

    def _copy_tr(self) -> None:
        t = self._translation or self._text
        if not t:
            return
        try:
            pyperclip.copy(t)
            if self._status_lbl:
                self._status_lbl.configure(text="скопировано")
        except Exception:  # noqa: BLE001
            logutil.exc("copy")

    def _open_main(self) -> None:
        text = self._text
        logutil.get().info("mini → main len=%s", len(text))
        self.hide()
        if text and self._on_open_main:
            try:
                self._on_open_main(text)
            except Exception:  # noqa: BLE001
                logutil.exc("on_open_main")

    # ── geometry / visibility ───────────────────────────────
    def _set_visible(self, on: bool) -> None:
        self._visible = on
        if self._on_visibility:
            try:
                self._on_visibility(on)
            except Exception:  # noqa: BLE001
                pass

    def _place(self, w: int, h: int, x: int, y: int) -> None:
        self._cur_w, self._cur_h = w, h
        px, py = clamp_popup(int(x), int(y), w, h)
        if self._win is not None:
            try:
                self._win.geometry(f"{w}x{h}+{px}+{py}")
            except Exception:  # noqa: BLE001
                logutil.exc("geometry")

    def _map_window(self) -> None:
        if self._win is None or not self._alive:
            return
        try:
            self._win.deiconify()
            self._win.lift()
            self._win.attributes("-topmost", True)
            self._win.update_idletasks()
            dpi.force_topmost(int(self._win.winfo_id()))
            logutil.get().info(
                "popup mapped mode=%s root=(%s,%s) geo=%s",
                self._mode,
                self._win.winfo_rootx(),
                self._win.winfo_rooty(),
                self._win.winfo_geometry(),
            )
        except Exception:  # noqa: BLE001
            logutil.exc("map_window")

    def _cancel_hide(self) -> None:
        if self._hide_after_id is not None:
            try:
                self._master.after_cancel(self._hide_after_id)
            except Exception:  # noqa: BLE001
                pass
            self._hide_after_id = None

    def _arm_hide(self, ms: int) -> None:
        self._cancel_hide()
        if not self._alive:
            return
        try:
            self._hide_after_id = self._master.after(ms, self.hide)
        except Exception:  # noqa: BLE001
            pass
