"""Google-style chivoblya pill + mini translation card near the selection.

Card dismisses on outside click (ready for next translate). Safe UI updates from threads.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable

import customtkinter as ctk
import pyperclip

from . import dpi
from . import languages as langs
from . import logutil
from . import settings as cfg
from . import theme as T
from .app_icon import apply as apply_app_icon
from . import translators as tr
from .selection import normalize_newlines
from .chip_styles import get_style
from .screen import clamp_popup, max_popup_size_at

try:
    import mouse
except ImportError:  # pragma: no cover
    mouse = None  # type: ignore

# default sizes; split chips a bit wider
CHIP_W, CHIP_H = 120, 36
CHIP_W_SPLIT = 148

# Card shrink-wraps to text (Lebedev: size = content, no empty air).
# Grows for long translations; scroll only past ~85% work-area height.
CARD_MIN_W = 240  # both foot pills must fit
CARD_MAX_W = 420
CARD_MIN_H = 72
CARD_WRAP_CHARS = 48  # max chars before wrap; short text uses fewer
CARD_LINE_H = 21
CARD_FOOT_H = 36
CARD_HEAD_H = 28
CARD_STATUS_H = 22
CARD_PAD_X = 10

# Card typography = main window typography. Sizes are logical px, scaled the
# way CustomTkinter scales a CTkFont (see _card_font). Raw tk point sizes are
# multiplied by `tk scaling` (~1.67 here) on top and come out a fifth taller.
CARD_BODY_FONT_SIZE = T.FONT_BODY_SIZE  # 13 — as in both text panes
CARD_HEAD_FONT_SIZE = 11  # as the source / acronyms captions
CARD_CLOSE_FONT_SIZE = 12
CARD_SMALL_FONT_SIZE = 11  # status line + foot pills
# head + foot + borders + body pads — foot must always fit inside geometry
CARD_CHROME_H = CARD_HEAD_H + CARD_FOOT_H + 16
# colors live in theme tokens — read T.* at paint time (theme can switch)


class ChivoblyaPopup:
    def __init__(
        self,
        master: tk.Misc,
        *,
        on_open_main: Callable[[str], None] | None = None,
        on_visibility: Callable[[bool], None] | None = None,
        on_chivoblya: Callable[[str], None] | None = None,
    ) -> None:
        self._master = master
        self._on_open_main = on_open_main
        self._on_visibility = on_visibility
        self._on_chivoblya = on_chivoblya
        self._text = ""
        self._translation = ""
        self._anchor = (0, 0)
        self._mode = "chip"

        self._win: tk.Toplevel | None = None
        self._chip_frame: tk.Frame | None = None
        self._card_frame: tk.Frame | None = None
        self._src_lbl: tk.Label | None = None
        self._tgt_text: tk.Text | None = None
        self._tgt_scroll: tk.Scrollbar | None = None
        self._tgt_font: tkfont.Font | None = None
        self._status_lbl: tk.Label | None = None
        self._card_body: tk.Frame | None = None
        self._card_foot: tk.Frame | None = None
        self._scroll_mode = False

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
        # global LMB → hide card when click is outside the popup
        self._outside_handlers: list = []
        self._outside_arm_id: str | None = None

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
        # new selection replaces open card/chip
        if self._visible and self._mode == "card":
            log.info("replace open card with new chip")
            self._disarm_outside_dismiss()
            self._cancel_hide()

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
            self._arm_outside_dismiss()
            log.info(
                "chip show len=%s at=(%s,%s) head=%r",
                len(text),
                x,
                y,
                logutil.head(text, 50),
            )
        except Exception:  # noqa: BLE001
            logutil.exc("popup.show")

    def hide(self) -> None:
        logutil.get().debug("popup.hide mode=%s", self._mode)
        self._cancel_hide()
        self._disarm_outside_dismiss()
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
    def _card_font(self, size: int, weight: str = "normal") -> tuple:
        """Main-window font at `size` logical px — negative tk size = pixels."""
        try:
            scale = float(ctk.ScalingTracker.get_widget_scaling(self._master))
        except Exception:  # noqa: BLE001
            scale = 1.0
        return (T.FONT_UI, -abs(round(size * (scale or 1.0))), weight)

    def _ensure_win(self) -> None:
        if self._win is not None:
            return
        win = tk.Toplevel(self._master)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=T.BG)
        win.withdraw()
        # don't destroy app if this window errors
        win.protocol("WM_DELETE_WINDOW", self.hide)

        chip_outer = tk.Frame(win, bg=T.BG)
        self._chip_host = chip_outer  # rebuilt per style on show
        self._rebuild_chip()

        # CARD
        card_outer = tk.Frame(win, bg=T.LINE)
        body = tk.Frame(card_outer, bg=T.SURFACE)
        body.pack(fill="both", expand=True, padx=1, pady=1)

        # row 1 (text) expands; foot stays pinned so buttons never clip
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)

        head = tk.Frame(body, bg=T.SURFACE)
        # the detected language name only, not the word "translation"
        lang_lbl = tk.Label(
            head,
            text="",
            font=self._card_font(CARD_HEAD_FONT_SIZE),
            fg=T.INK_SOFT,
            bg=T.SURFACE,
            anchor="w",
        )
        lang_lbl.pack(side="left", fill="x", expand=True)
        close = tk.Label(
            head,
            text="✕",
            font=self._card_font(CARD_CLOSE_FONT_SIZE),
            fg=T.INK_SOFT,
            bg=T.SURFACE,
            cursor="hand2",
        )
        close.pack(side="right")
        close.bind("<ButtonRelease-1>", lambda _e: self.hide())
        head.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 2))

        foot = tk.Frame(body, bg=T.CHIP_BG, height=CARD_FOOT_H)
        foot.grid(row=3, column=0, sticky="ew")
        foot.grid_propagate(False)
        actions = tk.Frame(foot, bg=T.CHIP_BG)
        actions.pack(padx=8, pady=5, anchor="w")

        # translation body — same size as the main window; grow window for long
        # text, scroll only at cap
        body_px = self._card_font(CARD_BODY_FONT_SIZE)[1]
        self._tgt_font = tkfont.Font(family=T.FONT_UI, size=body_px)
        tgt_outer = tk.Frame(body, bg=T.SURFACE)
        tgt_scroll = tk.Scrollbar(tgt_outer, orient="vertical")
        tgt = tk.Text(
            tgt_outer,
            font=self._tgt_font,
            fg=T.INK,
            bg=T.SURFACE,
            wrap="word",
            width=CARD_WRAP_CHARS,
            height=2,
            relief="flat",
            highlightthickness=0,
            borderwidth=0,
            padx=0,
            pady=0,
            cursor="arrow",
            spacing1=1,
            spacing3=1,
        )
        tgt.pack(side="left", fill="both", expand=True)
        tgt.configure(state="disabled")
        tgt.bind("<Key>", lambda _e: "break")
        tgt.tag_configure("read", background=T.READ_BG)
        tgt.bind("<MouseWheel>", self._on_tgt_wheel)
        tgt.bind("<Button-4>", self._on_tgt_wheel)  # Linux scroll up
        tgt.bind("<Button-5>", self._on_tgt_wheel)  # Linux scroll down
        tgt_outer.grid(row=1, column=0, sticky="nsew", padx=10, pady=(2, 4))

        status = tk.Label(
            body,
            text="",
            font=self._card_font(CARD_SMALL_FONT_SIZE),
            fg=T.INK_SOFT,
            bg=T.SURFACE,
            anchor="w",
        )
        status.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 2))

        self._make_pill(actions, "⎘  копировать", self._copy_tr).pack(side="left", padx=(0, 6))
        self._make_pill(actions, "↗  в окно", self._open_main).pack(side="left")

        self._win = win
        win.after(0, lambda: apply_app_icon(win))
        self._chip_frame = chip_outer
        self._card_frame = card_outer
        self._card_body = body
        self._card_foot = foot
        self._lang_lbl = lang_lbl
        self._src_lbl = None  # source text intentionally not shown
        self._tgt_text = tgt
        self._tgt_scroll = tgt_scroll
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
            # ── 1/3 eye | 2/3 chivoblya ──
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
            font=self._card_font(CARD_SMALL_FONT_SIZE),
            fg=ink,
            bg=bg,
            padx=8,
            pady=2,
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
        self._set_tgt_content("…", muted=True)
        if getattr(self, "_lang_lbl", None):
            self._lang_lbl.configure(text="(…)")
        if self._status_lbl:
            self._status_lbl.configure(text="")
            try:
                self._status_lbl.grid_remove()
            except Exception:  # noqa: BLE001
                pass
        self._cur_w = CARD_MIN_W
        self._cur_h = CARD_MIN_H
        body = getattr(self, "_card_body", None)
        if body is not None:
            try:
                body.grid_rowconfigure(1, weight=0)
            except Exception:  # noqa: BLE001
                pass
        self._place(self._cur_w, self._cur_h, *self._anchor)
        self._map_window()
        self._arm_outside_dismiss()

    # ── outside click → dismiss chip/card ───────────────────
    def _arm_outside_dismiss(self) -> None:
        """LMB outside popup hides chip or card. Short delay so open-click doesn't close it."""
        self._disarm_outside_dismiss()
        if mouse is None or not self._alive:
            return

        def arm() -> None:
            self._outside_arm_id = None
            if not self._alive or not self._visible:
                return
            if self._outside_handlers:
                return

            def on_down() -> None:
                if not self._alive or not self._visible:
                    return
                try:
                    x, y = mouse.get_position()
                except Exception:  # noqa: BLE001
                    return
                if self.contains_screen_point(x, y):
                    return
                logutil.get().info(
                    "outside click → hide mode=%s at=(%s,%s)", self._mode, x, y
                )
                try:
                    self._master.after(0, self.hide)
                except Exception:  # noqa: BLE001
                    pass

            try:
                self._outside_handlers.append(
                    mouse.on_button(on_down, buttons=("left",), types=("down",))
                )
                logutil.get().debug("outside dismiss armed")
            except Exception:  # noqa: BLE001
                logutil.exc("arm outside dismiss")

        try:
            # Grace past the mouse-up that opened the chip; then LMB elsewhere hides.
            self._outside_arm_id = self._master.after(400, arm)
        except Exception:  # noqa: BLE001
            pass

    def _disarm_outside_dismiss(self) -> None:
        if self._outside_arm_id is not None:
            try:
                self._master.after_cancel(self._outside_arm_id)
            except Exception:  # noqa: BLE001
                pass
            self._outside_arm_id = None
        if mouse is None:
            self._outside_handlers.clear()
            return
        for h in self._outside_handlers:
            try:
                mouse.unhook(h)
            except Exception:  # noqa: BLE001
                pass
        self._outside_handlers.clear()

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
        """2/3 chivoblya: open main window only — no mini card."""
        if not self._alive or self._click_guard:
            return
        if not self._visible or self._mode != "chip":
            return
        self._click_guard = True
        text = self._text
        logutil.get().info("CHIVOBLYA click → main window len=%s", len(text))
        try:
            self.hide()
            cb = self._on_chivoblya or self._on_open_main
            if text and cb:
                cb(text)
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
        # Direction follows the text: an explicit ru→en pair handed English
        # would otherwise be asked to translate English into English.
        want = langs.effective_target(target, source, text)
        if want and want != target:
            source, target = target, want
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
                self._set_tgt_content("не удалось перевести", error=True)
                if self._status_lbl:
                    self._status_lbl.configure(text=(result.error or "ошибка")[:70])
                log.warning("mini tr fail: %s", result.error)
                self._resize_card_for_tgt()
                self._place(self._cur_w, self._cur_h, *self._anchor)
                self._map_window()
                self._arm_hide(15000)
                return

            self._translation = normalize_newlines(result.text)
            # header: the detected source language, not the word "translation"
            src_code = result.detected_source or cfg.get().source_lang or "auto"
            if getattr(self, "_lang_lbl", None):
                self._lang_lbl.configure(text=f"({short_ru(src_code)})")
            self._set_tgt_content(self._translation)
            if self._status_lbl:
                self._status_lbl.configure(text="")

            self._resize_card_for_tgt()
            self._place(self._cur_w, self._cur_h, *self._anchor)
            self._map_window()
            # refresh lifetime after success
            self._arm_hide(45000)
            log.info(
                "mini tr ok len=%s size=%sx%s head=%r",
                len(self._translation),
                self._cur_w,
                self._cur_h,
                logutil.head(self._translation, 60),
            )
        except Exception:  # noqa: BLE001
            logutil.exc("apply_tr UI")

    def _set_tgt_content(
        self,
        text: str,
        *,
        muted: bool = False,
        error: bool = False,
    ) -> int:
        w = self._tgt_text
        if w is None:
            return 2
        color = T.ERR if error else (T.INK_SOFT if muted else T.INK)
        w.configure(state="normal", fg=color)
        w.delete("1.0", "end")
        w.tag_remove("read", "1.0", "end")
        if text:
            w.insert("1.0", text)
        w.configure(state="disabled")
        try:
            w.update_idletasks()
            lines = int(w.count("1.0", "end-1c", "displaylines")[0])
        except Exception:  # noqa: BLE001
            lines = max(1, 1 + len(text) // CARD_WRAP_CHARS)
        return max(1, lines)

    def _content_text_width_px(self, text: str) -> int:
        """Pixel width of longest source line (pre-wrap)."""
        font = self._tgt_font
        if not text:
            return 40
        lines = text.splitlines() or [text]
        if font is None:
            return max(len(ln) for ln in lines) * 7
        return max(int(font.measure(ln)) for ln in lines)

    def _estimate_wrapped_lines(self, text: str, inner_px: int) -> int:
        """Font-measure wrap count — reliable when Text.count(displaylines) is None/wrong.

        Word-aware on purpose: `wrap="word"` never splits a word, so filling the
        line char by char fits more per line than Tk does and the card comes out
        a line short — with the last line cut off.
        """
        if not text:
            return 1
        font = self._tgt_font
        inner_px = max(int(inner_px), 40)
        total = 0
        for para in text.split("\n"):
            total += 1
            if not para:
                continue
            if font is None:
                # ~avg char width 7px
                total += max(1, (len(para) * 7 + inner_px - 1) // inner_px) - 1
                continue
            space_w = int(font.measure(" "))
            line_w = 0
            for word in para.split(" "):
                word_w = int(font.measure(word))
                add = word_w if line_w == 0 else space_w + word_w
                if line_w and line_w + add > inner_px:
                    total += 1
                    line_w = word_w
                else:
                    line_w += add
                while line_w > inner_px:  # a single word wider than the line
                    total += 1
                    line_w -= inner_px
        return max(1, total)

    def _count_display_lines(self, text: str, wrap_chars: int, inner_px: int) -> int:
        """Font-measure wrap only.

        Tk Text.count('displaylines') is unreliable here: unmapped / pre-geometry
        widgets report one-char width → N chars become N lines (horse-sized card).
        """
        return self._estimate_wrapped_lines(text, inner_px)

    def _resize_card_for_tgt(self) -> None:
        """Shrink-wrap to text (Lebedev: size = content). Scroll only at monitor cap.

        Never seed a tall geometry then measure — with row weight=1 the body
        expands to the seed and the card becomes a white skyscraper.
        """
        if self._tgt_text is None or self._win is None:
            return

        text = self._translation or ""
        if not text:
            try:
                text = self._tgt_text.get("1.0", "end-1c")
            except Exception:  # noqa: BLE001
                text = ""

        ax, ay = self._anchor
        mon_w, mon_h = max_popup_size_at(ax, ay, frac=0.85)
        max_card_w = min(CARD_MAX_W, mon_w)
        max_card_h = max(mon_h, CARD_MIN_H)

        font = self._tgt_font
        zero_w = max(int(font.measure("0")) if font else 7, 6)
        line_h = max(int(font.metrics("linespace")) if font else CARD_LINE_H, 14)

        pad_x = CARD_PAD_X * 2 + 2
        content_px = self._content_text_width_px(text)
        want_w = content_px + pad_x + 8
        card_w = max(CARD_MIN_W, min(want_w, max_card_w))
        inner_px = max(card_w - pad_x, 40)

        wrap_chars = max(8, min(CARD_WRAP_CHARS, inner_px // zero_w))
        self._tgt_text.configure(width=wrap_chars)

        status_h = 0
        if self._status_lbl is not None:
            st = (self._status_lbl.cget("text") or "").strip()
            try:
                if st:
                    self._status_lbl.grid()
                    status_h = CARD_STATUS_H
                else:
                    self._status_lbl.grid_remove()
            except Exception:  # noqa: BLE001
                pass

        display_lines = max(1, self._count_display_lines(text, wrap_chars, inner_px))
        scroll = self._tgt_scroll
        body = getattr(self, "_card_body", None)

        # Content height from lines — not from an expanded parent
        natural_body = display_lines * line_h + 8
        natural_h = CARD_HEAD_H + natural_body + status_h + CARD_FOOT_H + 6

        if natural_h <= max_card_h:
            # Shrink-wrap: no expand weight (otherwise empty air under short text)
            if body is not None:
                try:
                    body.grid_rowconfigure(1, weight=0)
                except Exception:  # noqa: BLE001
                    pass
            self._tgt_text.configure(height=display_lines)
            if scroll is not None:
                self._tgt_text.configure(yscrollcommand=None)
                scroll.pack_forget()
            self._scroll_mode = False
            # Prefer Text reqheight when it agrees with line count (±1 line)
            body_h = natural_body
            try:
                self._tgt_text.update_idletasks()
                req = int(self._tgt_text.winfo_reqheight())
                lo = display_lines * line_h - line_h
                hi = display_lines * line_h + line_h + 8
                if lo <= req <= hi:
                    body_h = req + 6
            except Exception:  # noqa: BLE001
                pass
            card_h = max(CARD_MIN_H, CARD_HEAD_H + body_h + status_h + CARD_FOOT_H + 6)
            # Safety: never exceed monitor; if we would, fall through to scroll path
            if card_h > max_card_h:
                natural_h = card_h  # trigger scroll branch below
            else:
                self._cur_w = card_w
                self._cur_h = card_h
                self._update_read_highlight()
                return

        # Cap to monitor — pin foot, body expands + scrolls
        card_h = max_card_h
        self._scroll_mode = True
        if body is not None:
            try:
                body.grid_rowconfigure(1, weight=1)
            except Exception:  # noqa: BLE001
                pass
        max_body_h = max(line_h, card_h - CARD_CHROME_H - status_h)
        visible_lines = max(1, max_body_h // line_h)
        self._tgt_text.configure(height=visible_lines)
        if scroll is not None:
            scroll.pack(side="right", fill="y")
            self._tgt_text.configure(yscrollcommand=self._on_tgt_yscroll)
            scroll.configure(command=self._tgt_text.yview)
            card_w = min(max(card_w + 14, CARD_MIN_W), max_card_w)

        self._cur_w = card_w
        self._cur_h = card_h
        self._update_read_highlight()

    def _on_tgt_yscroll(self, first: str, last: str) -> None:
        scroll = self._tgt_scroll
        if scroll is not None:
            scroll.set(first, last)
        self._update_read_highlight()

    def _on_tgt_wheel(self, event) -> str | None:
        w = self._tgt_text
        if w is None or not self._scroll_mode:
            return None
        try:
            delta = int(-1 * (event.delta / 120)) if getattr(event, "delta", 0) else 0
            if delta == 0:
                delta = -1 if event.num == 5 else 1
            w.yview_scroll(delta, "units")
            self._update_read_highlight()
        except Exception:  # noqa: BLE001
            pass
        return "break"

    def _update_read_highlight(self) -> None:
        """Experimental: tint text above the viewport while scrolling."""
        w = self._tgt_text
        if w is None or not self._scroll_mode or not self._translation:
            return
        try:
            top = w.index("@0,0")
            if not top or top == "1.0":
                w.tag_remove("read", "1.0", "end")
                return
            w.configure(state="normal")
            w.tag_remove("read", "1.0", "end")
            w.tag_add("read", "1.0", top)
            w.configure(state="disabled")
        except Exception:  # noqa: BLE001
            pass

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
        # Cap to monitor work area so geometry never claims more than can fit
        max_w, max_h = max_popup_size_at(int(x), int(y), frac=0.9)
        w = max(1, min(int(w), max_w))
        h = max(CARD_MIN_H if self._mode == "card" else 1, min(int(h), max_h))
        # Hard ceiling: never taller than 85% work area for cards (anti-skyscraper)
        if self._mode == "card":
            _mw, mh = max_popup_size_at(int(x), int(y), frac=0.85)
            h = min(h, mh)
        self._cur_w, self._cur_h = w, h
        px, py = clamp_popup(int(x), int(y), w, h)
        if self._win is None:
            return
        try:
            self._win.geometry(f"{w}x{h}+{px}+{py}")
            self._win.update_idletasks()
        except Exception:  # noqa: BLE001
            logutil.exc("geometry")
            return
        # If foot clipped on shrink-wrap, bump a little (not to monitor max)
        if self._mode != "card" or self._scroll_mode:
            return
        foot = getattr(self, "_card_foot", None)
        if foot is None:
            return
        try:
            foot.update_idletasks()
            need_bottom = int(foot.winfo_y()) + int(foot.winfo_height()) + 2
            got = int(self._win.winfo_height())
            if need_bottom <= got + 1:
                return
            grow = min(need_bottom - got + 2, 48)  # small pad only — never skyscrape
            new_h = min(h + grow, max_h)
            if new_h <= h:
                return
            self._cur_h = new_h
            px, py = clamp_popup(int(x), int(y), w, new_h)
            self._win.geometry(f"{w}x{new_h}+{px}+{py}")
        except Exception:  # noqa: BLE001
            logutil.exc("geometry verify foot")

    def _map_window(self) -> None:
        if self._win is None or not self._alive:
            return
        try:
            self._win.deiconify()
            self._win.lift()
            self._win.attributes("-topmost", True)
            self._win.update_idletasks()
            hwnd = 0
            frame = 0
            try:
                from . import winframe

                hwnd = int(winframe.hwnd_of(self._win) or 0)
            except Exception:  # noqa: BLE001
                hwnd = 0
            try:
                frame = int(str(self._win.wm_frame()), 16)
            except Exception:  # noqa: BLE001
                frame = 0
            # Prefer outer frame / parent — raw winfo_id is often an inner child.
            for h in (frame, hwnd, int(self._win.winfo_id() or 0)):
                if h:
                    dpi.force_topmost(int(h))
            logutil.get().info(
                "popup mapped mode=%s root=(%s,%s) geo=%s",
                self._mode,
                self._win.winfo_rootx(),
                self._win.winfo_rooty(),
                self._win.winfo_geometry(),
            )
            # Firefox can steal z-order right after deiconify — re-pin twice.
            try:
                self._master.after(50, self._reassert_topmost)
                self._master.after(200, self._reassert_topmost)
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            logutil.exc("map_window")

    def _reassert_topmost(self) -> None:
        if self._win is None or not self._alive or not self._visible:
            return
        try:
            self._win.attributes("-topmost", True)
            self._win.lift()
            from . import winframe

            h = int(winframe.hwnd_of(self._win) or 0)
            try:
                frame = int(str(self._win.wm_frame()), 16)
            except Exception:  # noqa: BLE001
                frame = 0
            for cand in (frame, h):
                if cand:
                    dpi.force_topmost(int(cand))
        except Exception:  # noqa: BLE001
            pass

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
