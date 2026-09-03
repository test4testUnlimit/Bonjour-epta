"""Main dual-pane — native Windows caption, Segoe UI / UTF-8."""

from __future__ import annotations

import threading
from collections.abc import Callable

import customtkinter as ctk
import pyperclip

from . import acronyms
from . import ai_client, ai_config, ai_token, assistant
from . import languages as langs
from . import logutil
from . import settings as cfg
from . import theme as T
from . import translators as tr
from .acro_panel import AcronymPanel
from .ai_panel import AiPanel
from .restart import schedule_relaunch
from .screen import center_on_screen
from .selection import normalize_newlines
from . import spotlight
from .settings_ui import SettingsWindow
from .theme import apply_appearance, apply_theme, mdl2_font, ui_font
from .app_icon import apply as apply_app_icon
from .ui_widgets import tune_combobox
from .translators.base import TranslateResult

apply_appearance()

APP_VERSION = T.APP_VERSION

# Auto-update check: once a day, and never during the logon rush.
AUTO_CHECK_DELAY_MS = 60_000
AUTO_CHECK_EVERY_MS = 6 * 3_600_000  # re-arm; the real 24h gate is updater.due()


class TranslatorApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        s = cfg.load()
        apply_theme(s.ui_theme)
        # native Windows caption, empty title text
        self.title("")
        # the ⇄ is pinned to the pane split, so both toolbar flanks are mirrored
        # to the same width: the widest one (west, ~500px: brand ↻ Google 📚
        # translate) is paid for twice, + 52 for the ⇄ column + 20 padding.
        # Below ~1075 the west flank starts clipping the translate pill, hence 1090.
        self.geometry("1120x600")
        self.minsize(1090, 460)
        self.configure(fg_color=T.BG)
        self._theme_pref = s.ui_theme

        self._maximized = False
        self._restore_geom = "1000x580+120+80"
        self._drag = {"x": 0, "y": 0}
        self._tray = None
        self._hiding_to_tray = False

        self._source_lang = ctk.StringVar(value=s.source_lang or "auto")
        self._target_lang = ctk.StringVar(value=s.target_lang or "ru")
        self._provider = ctk.StringVar(value=s.provider_id or tr.DEFAULT_PROVIDER_ID)
        self._status = ctk.StringVar(value="готов")
        self._busy = False
        self._settings_win: SettingsWindow | None = None
        self._translate_job = 0
        self._progress_after_id: str | None = None
        self._progress_tick = 0
        self._tgt_progress = False
        self._progress_word = "переводим"
        self._ai_job = 0
        self._token_after_id: str | None = None

        # dictionaries load off the UI thread — first explain() just waits for it
        self._acro_packs = dict(s.acronym_packs or {})
        acronyms.set_enabled(self._acro_packs)
        acronyms.warm()

        self._shell = ctk.CTkFrame(
            self, fg_color=T.BG, border_width=0, corner_radius=0
        )
        self._shell.pack(fill="both", expand=True)

        self._build(self._shell)
        self._setup_sync_scroll()
        self._setup_spotlight()
        # Start dead-centre: a bare geometry() leaves the top-left to the
        # window manager, which lands the window up-and-left of centre.
        # Centre once the window is actually MAPPED, not on a fixed delay:
        # before that winfo_width() is still 1, and centring on a 1px window
        # puts the top-left corner in the middle of the screen (3.3.2 laptop).
        self._centered_once = False
        self.bind("<Map>", self._center_on_first_map, add="+")
        # subscribed once, not per _build — a theme switch rebuilds every widget
        # but _sync_ai_group looks them up fresh each time it runs
        ai_token.on_change(self._on_token_change)
        self._watch_token()
        cfg.on_change(self._on_settings_changed)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Unmap>", self._on_unmap)
        # Window-level net: Ctrl+V while focus sits on a button/frame still
        # pastes into the source box (fires only if no widget handled it).
        self.bind("<Control-KeyPress>", self._on_window_ctrl_key)

        self.after(80, lambda: apply_app_icon(self))
        # Quiet daily check, well after the logon rush.
        self.after(AUTO_CHECK_DELAY_MS, self._auto_check_updates)

        label = next(
            (lb for pid, lb, _ in tr.list_providers() if pid == self._provider.get()),
            None,
        )
        if label:
            self._provider_combo.set(label)

    def _center_on_first_map(self, event) -> None:
        if event is not None and event.widget is not self:
            return
        if self._centered_once:
            return
        self._centered_once = True
        center_on_screen(self)

    def _on_unmap(self, event) -> None:
        if event.widget is not self:
            return
        if self._hiding_to_tray:
            return
        try:
            if str(self.state()) == "iconic":
                self.after(0, self._minimize_to_tray)
        except Exception:  # noqa: BLE001
            pass

    def _minimize_to_tray(self) -> None:
        self._hiding_to_tray = True
        try:
            self.withdraw()
        finally:
            self._hiding_to_tray = False

    def _minimize(self) -> None:
        """Public minimize = hide to tray (also used by --startup)."""
        self._minimize_to_tray()

    def show_from_tray(self) -> None:
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
            apply_app_icon(self)
            # Focus source box so Ctrl+V works immediately
            try:
                self._inner(self._src_box).focus_set()
            except Exception:
                pass
        except Exception:  # noqa: BLE001
            pass

    def _toggle_max(self) -> None:
        try:
            if self.state() == "zoomed":
                self.state("normal")
            else:
                self.state("zoomed")
        except Exception:  # noqa: BLE001
            pass

    def _build(self, parent: ctk.CTkFrame) -> None:
        """
        Full-width toolbar (3-col grid) + 3-col pane grid, sharing one axis:
          [ brand ↻ Google 📚 translate ][ ⇄ ][ clear AI ⚙ ]  ← content width
          [ source pane ]      |  MID_W  |      [ target pane ]  ← mirror panes
        The ⇄ column is the middle one, so it lands exactly over the pane split.
        Tools must not live only in the right pane column (overflow → paint-over).
        """
        content = ctk.CTkFrame(parent, fg_color=T.BG)
        content.pack(fill="both", expand=True, padx=T.PAD, pady=(T.GAP, 0))

        # ── toolbar: 3 grid columns, one optical axis ─────────────────────
        #   col0 (weight 1) │ col1 = ⇄ │ col2 (weight 1)
        # Both flanks share a uniform group, so they are always equally wide and
        # the ⇄ sits dead centre of the content — the same centre as the MID_W
        # gap between the panes below it.
        # Not place(relx=0.5) — that floats over the row and painted over
        # the explain button on a narrow window. Grid columns reserve space, so
        # nothing can ever be drawn on top of anything else.
        # Every cell is ROW_H tall and centred in HEAD_H (vpad), including the
        # brand: it used to be bottom-anchored (sticky="s") and sat ~8px below
        # every pill next to it.
        toolbar = ctk.CTkFrame(content, fg_color="transparent", height=T.HEAD_H)
        toolbar.pack(fill="x", pady=(0, T.GAP))
        toolbar.grid_propagate(False)
        toolbar.grid_rowconfigure(0, weight=1)
        toolbar.grid_columnconfigure(0, weight=1, uniform="flank")
        toolbar.grid_columnconfigure(1, weight=0)
        toolbar.grid_columnconfigure(2, weight=1, uniform="flank")

        vpad = (T.HEAD_H - T.ROW_H) // 2
        icon_pad = (T.HEAD_H - 26) // 2

        west = ctk.CTkFrame(toolbar, fg_color="transparent")
        west.grid(row=0, column=0, sticky="nsew")
        east = ctk.CTkFrame(toolbar, fg_color="transparent")
        east.grid(row=0, column=2, sticky="nsew")

        # — ⇄ swap (6): middle column = the pane split, top of the window —
        self._btn_swap = ctk.CTkButton(
            toolbar,
            text="⇄",
            width=T.SWAP_W,
            height=T.ROW_H,
            corner_radius=T.ROW_H // 2,
            font=ui_font(16),
            fg_color=T.SURFACE,
            border_width=1,
            border_color=T.LINE,
            hover_color=T.CHIP_HOVER,
            text_color=T.INK,
            command=self.swap_direction,
        )
        self._btn_swap.grid(row=0, column=1, padx=T.TOOL_GAP)

        # ── east flank — reads clear · AI · ⚙ ─────────────────────────────
        # — clear (7) hugs the west edge of its column, mirroring
        #   translate on the other side: both sit one TOOL_GAP off the ⇄
        #   (the gap is the ⇄ cell's own padx), whatever the window width —
        self._ghost(east, "очистить", self.clear_all, w=80).pack(
            side="left", pady=vpad,
        )

        # — ⚙ settings (far right, flush with the content edge) —
        self._settings_btn(east).pack(side="right", pady=vpad)

        # — AI group (8) —
        self._build_ai_group(east).pack(side="right", padx=(0, T.TOOL_GAP), pady=vpad)

        # ── west flank — brand ↻ · Google ● · 📚 from the left, translate at the ⇄
        # — translate (5) hugs the east edge of its column: packed first so a
        #   narrow window eats into the middle of the flank, not into the pill —
        self._btn_translate = ctk.CTkButton(
            west,
            text="перевести",
            width=96,
            height=T.ROW_H,
            corner_radius=T.ROW_H // 2,
            fg_color=T.ACCENT,
            hover_color=T.ACCENT_HOVER,
            text_color=T.ON_ACCENT,
            font=ui_font(13, "bold"),
            command=self.translate_now,
        )
        self._btn_translate.pack(side="right", pady=vpad)

        # — brand mark (1) + check for updates (2) —
        mark = ctk.CTkFrame(west, fg_color="transparent", height=T.HEAD_H)
        mark.pack(side="left", fill="y")
        # one full-height row + sticky="" → every child rides the same centre
        # line as the pills to its right
        mark.grid_rowconfigure(0, weight=1)
        ctk.CTkLabel(
            mark,
            text="Bonjour",
            font=ui_font(T.FONT_BRAND_SIZE),
            text_color=T.INK,
        ).grid(row=0, column=0, sticky="")
        ctk.CTkLabel(
            mark,
            text=f" {T.BRAND_CYR}",
            font=ui_font(T.FONT_BRAND_CYR_SIZE, "bold"),
            text_color=T.INK,
        ).grid(row=0, column=1, sticky="")
        # bottom pad on a centred cell = lift: the version rides as a superscript
        ctk.CTkLabel(
            mark,
            text=f" {APP_VERSION}",
            font=ui_font(T.FONT_VERSION_SIZE),
            text_color=T.INK_SOFT,
        ).grid(row=0, column=2, sticky="", pady=(0, 10))
        # circular arrow — check the public release feed (was: hard relaunch)
        ctk.CTkButton(
            mark,
            text=T.GLYPH_RESTART,
            font=mdl2_font(13),
            width=26,
            height=26,
            corner_radius=13,
            fg_color="transparent",
            hover_color=T.CHIP_HOVER,
            text_color=T.INK_SOFT,
            border_width=0,
            command=self._check_updates,
        ).grid(row=0, column=3, sticky="", padx=(T.TOOL_GAP, 0))

        # — provider combo + dot (3) —
        prov_wrap = ctk.CTkFrame(west, fg_color="transparent", height=T.ROW_H)
        prov_wrap.pack(side="left", padx=(T.GAP, 0), pady=vpad)
        self._provider_map = {label: pid for pid, label, _ in tr.list_providers()}
        provider_labels = [label for _, label, _ in tr.list_providers()]
        default_label = next(
            label for pid, label, _ in tr.list_providers() if pid == self._provider.get()
        )
        self._provider_combo = ctk.CTkComboBox(
            prov_wrap,
            values=provider_labels,
            width=T.PROVIDER_COMBO_W,
            height=T.ROW_H,
            command=self._on_provider_ui,
            **self._combo_style(),
        )
        self._provider_combo.set(default_label)
        self._provider_combo.pack(side="left")
        tune_combobox(self._provider_combo)

        self._provider_dot = ctk.CTkLabel(
            prov_wrap,
            text="●",
            width=T.DOT_SIZE + 4,
            height=T.ROW_H,
            font=ui_font(T.DOT_SIZE),
            text_color=T.INK_FAINT,
            anchor="center",
        )
        # the dot belongs to the combo — kept tighter than the inter-tool gap
        self._provider_dot.pack(side="left", padx=(6, 0))

        # — book stack (4): the dictionary in one click, no acronym needed —
        ctk.CTkButton(
            west,
            text=T.GLYPH_DICT,
            font=mdl2_font(14),
            width=26,
            height=26,
            corner_radius=13,
            fg_color="transparent",
            hover_color=T.CHIP_HOVER,
            text_color=T.INK_SOFT,
            border_width=0,
            command=lambda: self.open_acro_window(),
        ).pack(side="left", padx=(T.TOOL_GAP, 0), pady=icon_pad)

        # ── panes: 3-col grid, gap = MID_W only ─────────────
        panes = ctk.CTkFrame(content, fg_color=T.BG)
        panes.pack(fill="both", expand=True)
        panes.grid_columnconfigure(0, weight=1, uniform="pane")
        panes.grid_columnconfigure(1, weight=0, minsize=T.MID_W)
        panes.grid_columnconfigure(2, weight=1, uniform="pane")
        panes.grid_rowconfigure(0, weight=1)

        self._left = self._make_pane(panes, "source")
        self._left.grid(row=0, column=0, sticky="nsew")

        ctk.CTkFrame(panes, fg_color=T.BG, width=T.MID_W).grid(
            row=0, column=1, sticky="nsew"
        )

        self._right = self._make_pane(panes, "target")
        self._right.grid(row=0, column=2, sticky="nsew")

        # AI answer strip, then the acronym strip — both full width under the
        # panes, both packed only when they have something; the panes give up
        # the height and the footer, living in `parent`, does not move
        self._ai_panel = AiPanel(content)
        self._acro = AcronymPanel(content, on_open_dict=self.open_acro_window)

        # footer: tagline left · hotkey right (no status in the middle)
        foot = ctk.CTkFrame(parent, fg_color=T.BG, height=T.FOOT_H)
        foot.pack(fill="x", padx=T.PAD, pady=(T.GAP, T.PAD))
        foot.pack_propagate(False)
        foot.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            foot,
            text=T.TAGLINE,
            text_color=T.INK_FAINT,
            font=ui_font(10),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        self._hk_foot = ctk.CTkLabel(
            foot,
            text=self._hotkey_footer(),
            text_color=T.INK_FAINT,
            font=ui_font(10),
            anchor="e",
        )
        self._hk_foot.grid(row=0, column=0, sticky="e")

        # kept for logic; not shown in footer
        self._status_lbl = ctk.CTkLabel(
            foot,
            textvariable=self._status,
            text_color=T.INK_FAINT,
            font=ui_font(10),
        )

        self.bind("<Control-Return>", lambda _e: self.translate_now())
        self.bind("<Control-l>", lambda _e: self.clear_all())
        self.after(200, self._probe_provider)

    def _hotkey_footer(self) -> str:
        try:
            spec = cfg.get().hotkey_spec()
            return f"{spec.mode_ru()} · {spec.label()}"
        except Exception:  # noqa: BLE001
            return ""

    def _make_pane(self, parent: ctk.CTkFrame, side: str) -> ctk.CTkFrame:
        """Identical card for source and target — one bar row + text field."""
        role = "исходник" if side == "source" else "перевод"
        frame = ctk.CTkFrame(
            parent,
            fg_color=T.SURFACE,
            corner_radius=T.CORNER,
            border_width=1,
            border_color=T.LINE,
        )
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        bar = ctk.CTkFrame(frame, fg_color="transparent", height=T.BAR_H)
        bar.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=T.INSET,
            pady=(T.INSET, T.BAR_GAP),
        )
        bar.grid_columnconfigure(1, weight=1)
        bar.grid_propagate(False)

        # the stretchy middle column: keep air on both sides so a long role or a
        # narrow pane never lets the caption touch the combo or the buttons
        ctk.CTkLabel(
            bar,
            text=role,
            font=ui_font(11),
            text_color=T.INK_FAINT,
            anchor="center",
        ).grid(row=0, column=1, sticky="ew", padx=T.BTN_GAP)

        btns = ctk.CTkFrame(bar, fg_color="transparent")
        btns.grid(row=0, column=2, sticky="e")

        combo_kw = dict(
            width=T.LANG_COMBO_W,
            height=T.ROW_H,
            **self._combo_style(),
        )

        if side == "source":
            codes = langs.codes_for_source()
            self._src_label_to_code = {langs.label_of(c): c for c in codes}
            self._src_combo = ctk.CTkComboBox(
                bar,
                values=[langs.label_of(c) for c in codes],
                command=lambda v: self._on_src_lang(v),
                **combo_kw,
            )
            self._src_combo.set(langs.label_of(self._source_lang.get()))
            self._src_combo.grid(row=0, column=0, sticky="w")
            tune_combobox(self._src_combo)
            self._clear_icon(btns, self.clear_source).pack(
                side="right", padx=(T.BTN_GAP, 0)
            )
            self._icon(btns, "копир.", self.copy_source, T.COPY_W).pack(side="right")

            self._src_box = self._textbox(frame)
            self._src_box.grid(
                row=1, column=0, sticky="nsew", padx=T.INSET, pady=(0, T.INSET)
            )
            # Bind paste on inner tk.Text so Ctrl+V reliably reaches the handler
            _inner_src = self._inner(self._src_box)
            self._bind_clipboard_keys(_inner_src)
            # Auto-focus source box so paste works immediately. A theme switch
            # rebuilds this pane, but the timer it left behind still fires — and
            # Tk does not cancel it just because the widget was destroyed.
            self._src_box.after(100, lambda w=_inner_src: self._focus_if_alive(w))
        else:
            codes = langs.codes_for_target()
            self._tgt_label_to_code = {langs.label_of(c): c for c in codes}
            self._tgt_combo = ctk.CTkComboBox(
                bar,
                values=[langs.label_of(c) for c in codes],
                command=lambda v: self._on_tgt_lang(v),
                **combo_kw,
            )
            self._tgt_combo.set(langs.label_of(self._target_lang.get()))
            self._tgt_combo.grid(row=0, column=0, sticky="w")
            tune_combobox(self._tgt_combo)
            self._clear_icon(btns, self.clear_target).pack(
                side="right", padx=(T.BTN_GAP, 0)
            )
            self._icon(btns, "копир.", self.copy_target, T.COPY_W).pack(side="right")

            self._tgt_box = self._textbox(frame)
            self._tgt_box.grid(
                row=1, column=0, sticky="nsew", padx=T.INSET, pady=(0, T.INSET)
            )
            # Ctrl+C on the translation: Tk's own <Control-c> never fires on a
            # Cyrillic layout, so the most-copied box in the app was dead there
            self._bind_copy_keys(self._inner(self._tgt_box))

        if side == "target":
            self._tgt_pane = frame
        else:
            self._src_pane = frame

        return frame

    def _setup_spotlight(self) -> None:
        """Selecting text in one pane highlights its translation in the other.

        Debounced <<Selection>> → translate the fragment off-thread → tag the
        matching substring in the twin pane. If the engine's rendering of the
        fragment is not found verbatim (a name, a number, a reworded phrase),
        the footer shows a "?" so the user knows the mapping failed.
        """
        self._spot_job = 0
        self._spot_after = None
        try:
            src = self._inner(self._src_box)
            tgt = self._inner(self._tgt_box)
            for w, other, direction in (
                (src, tgt, "src2tgt"),
                (tgt, src, "tgt2src"),
            ):
                w.tag_config(
                    spotlight.TAG, background=T.SPOT_BG, foreground=T.SPOT_INK
                )
                # `sel` already exists on the widget, so our tag sits below it
                # and the selection colour wins wherever they overlap. Raise it.
                w.tag_raise(spotlight.TAG)
                w.bind(
                    "<<Selection>>",
                    lambda e, me=w, twin=other, d=direction: self._on_spot_select(me, twin, d),
                    add="+",
                )
                # Double click = highlight the whole matching SENTENCE. Word-level
                # mapping is a guess (see spotlight docstring) and drifts by a word
                # or two; locating the translated sentence never does. So the
                # deliberate gesture gets the answer we can actually stand behind.
                w.bind(
                    "<Double-Button-1>",
                    lambda e, me=w, twin=other, d=direction: self._on_spot_sentence(me, twin, d),
                    add="+",
                )
        except Exception:  # noqa: BLE001
            logutil.exc("setup spotlight")

    def _on_spot_select(self, me, twin, direction: str) -> None:
        try:
            if not cfg.get().spotlight:
                return
        except Exception:  # noqa: BLE001
            return
        # debounce: dragging a selection fires <<Selection>> constantly
        if self._spot_after is not None:
            try:
                self.after_cancel(self._spot_after)
            except Exception:  # noqa: BLE001
                pass
        # Drop the stale highlight NOW. Waiting for the new result to arrive
        # (debounce + network) left the previous word lit for a visible beat,
        # which read as the highlight being stuck. Both panes: the last hit may
        # live in either one depending on which way the previous lookup went.
        self._spot_job += 1  # invalidate any in-flight lookup
        for w in (me, twin):
            try:
                w.tag_remove(spotlight.TAG, "1.0", "end")
            except Exception:  # noqa: BLE001
                pass
        try:
            if not me.tag_ranges("sel"):
                return  # selection cleared — nothing to look up
        except Exception:  # noqa: BLE001
            pass
        self._spot_after = self.after(
            350, lambda: self._run_spotlight(me, twin, direction)
        )

    @staticmethod
    def _char_offset(widget, index: str) -> int:
        """Char distance from 1.0 to index, tolerant of Tk's return shape."""
        try:
            raw = widget.count("1.0", index, "chars")
        except Exception:  # noqa: BLE001
            return 0
        if raw is None:
            return 0
        if isinstance(raw, (list, tuple)):
            raw = raw[0] if raw else 0
        try:
            return int(raw)
        except Exception:  # noqa: BLE001
            return 0

    def _on_spot_sentence(self, me, twin, direction: str) -> None:
        """Double click → highlight the whole counterpart sentence.

        Runs after Tk has already selected the double-clicked word, so the
        pending word-level lookup is cancelled first: otherwise its answer
        would land a moment later and shrink the highlight back to one word.
        """
        try:
            if not cfg.get().spotlight:
                return
        except Exception:  # noqa: BLE001
            return
        if self._spot_after is not None:
            try:
                self.after_cancel(self._spot_after)
            except Exception:  # noqa: BLE001
                pass
            self._spot_after = None
        self._spot_job += 1
        job = self._spot_job

        try:
            click = self._char_offset(me, "insert")
            src_whole = me.get("1.0", "end-1c")
            tgt_whole = twin.get("1.0", "end-1c")
            for w in (me, twin):
                w.tag_remove(spotlight.TAG, "1.0", "end")
        except Exception:  # noqa: BLE001
            logutil.exc("spot sentence read")
            return
        if not src_whole.strip() or not tgt_whole.strip():
            return

        if direction == "src2tgt":
            src_code = self._source_lang.get()
            tgt_code = self._target_lang.get()
        else:
            src_code = self._target_lang.get()
            tgt_code = self._source_lang.get()
            if tgt_code == "auto":
                tgt_code = "en"
        provider_id = self._provider.get()

        def work() -> None:
            try:
                span = spotlight.locate_sentence(
                    click, src_whole, tgt_whole, src_code, tgt_code, provider_id
                )
            except Exception:  # noqa: BLE001
                logutil.exc("spot sentence")
                span = None
            self.after(0, lambda: self._apply_sentence(twin, span, job))

        threading.Thread(target=work, daemon=True).start()

    def _apply_sentence(self, twin, span, job: int) -> None:
        if job != self._spot_job:
            return
        try:
            twin.tag_remove(spotlight.TAG, "1.0", "end")
            if not span:
                self._flash_foot("? предложение не найдено в переводе", False)
                return
            start, end = span
            twin.tag_add(spotlight.TAG, f"1.0+{start}c", f"1.0+{end}c")
            twin.see(f"1.0+{start}c")
        except Exception:  # noqa: BLE001
            logutil.exc("apply sentence")

    def _run_spotlight(self, me, twin, direction: str) -> None:
        self._spot_after = None
        self._spot_job += 1
        job = self._spot_job
        try:
            if not me.tag_ranges("sel"):
                twin.tag_remove(spotlight.TAG, "1.0", "end")
                return
            frag = me.get("sel.first", "sel.last").strip()
            src_whole = me.get("1.0", "end-1c")
            # Tk returns a 1-tuple here on most builds but a bare int on some;
            # normalising both keeps spotlight from dying silently.
            sel_start = self._char_offset(me, "sel.first")
            sel_end = self._char_offset(me, "sel.last")
            tgt_whole = twin.get("1.0", "end-1c")
        except Exception:  # noqa: BLE001
            logutil.exc("run spotlight read")
            return
        if not frag or not spotlight.words_only(frag) or not tgt_whole.strip():
            twin.tag_remove(spotlight.TAG, "1.0", "end")
            return

        if direction == "src2tgt":
            src_code = self._source_lang.get()
            tgt_code = self._target_lang.get()
        else:
            src_code = self._target_lang.get()
            tgt_code = self._source_lang.get()
            if tgt_code == "auto":
                tgt_code = "en"
        provider_id = self._provider.get()

        def work() -> None:
            try:
                span, approx = spotlight.align(
                    sel_start, sel_end, src_whole, tgt_whole,
                    src_code, tgt_code, provider_id,
                )
            except Exception:  # noqa: BLE001
                logutil.exc("spotlight align")
                span, approx = None, False
            self.after(0, lambda: self._apply_spotlight(me, twin, span, approx, job))

        threading.Thread(target=work, daemon=True).start()

    def _apply_spotlight(self, me, twin, span, approximate: bool, job: int) -> None:
        if job != self._spot_job:
            return
        try:
            twin.tag_remove(spotlight.TAG, "1.0", "end")
            # The answer may land after the user has already clicked the
            # selection away; painting then is exactly the "stuck highlight".
            try:
                if not me.tag_ranges("sel"):
                    return
            except Exception:  # noqa: BLE001
                pass
            if not span:
                self._flash_foot("? не удалось сопоставить с переводом", False)
                return
            start, end = span
            a = f"1.0+{start}c"
            b = f"1.0+{end}c"
            twin.tag_add(spotlight.TAG, a, b)
            twin.see(a)
            if approximate:
                self._flash_foot("≈ приблизительное место (движок перефразировал)", False)
        except Exception:  # noqa: BLE001
            logutil.exc("apply spotlight")

    def _setup_sync_scroll(self) -> None:
        """Link the two panes' vertical scroll so comparing long text keeps them aligned.

        Each inner tk.Text drives the other through yscrollcommand. A re-entry
        flag stops the ping-pong: setting pane B from pane A would otherwise
        fire B's command and loop forever. Proportional (first-visible-line)
        sync, not absolute — the two texts have different line counts.
        """
        self._sync_lock = False
        try:
            src = self._inner(self._src_box)
            tgt = self._inner(self._tgt_box)
        except Exception:  # noqa: BLE001
            return

        def _enabled() -> bool:
            try:
                return bool(cfg.get().sync_scroll)
            except Exception:  # noqa: BLE001
                return True

        def make_driver(other):
            def driver(*args):
                try:
                    if not _enabled() or self._sync_lock:
                        return
                    self._sync_lock = True
                    try:
                        first = float(args[0])
                        other.yview_moveto(first)
                    finally:
                        self._sync_lock = False
                except Exception:  # noqa: BLE001
                    self._sync_lock = False
            return driver

        try:
            # Chain onto the existing scrollbar commands so the stock scrollbar
            # still updates; we only mirror the position to the twin pane.
            src_sb = src.cget("yscrollcommand")
            tgt_sb = tgt.cget("yscrollcommand")

            src_drive = make_driver(tgt)
            tgt_drive = make_driver(src)

            def src_cmd(*args):
                if src_sb:
                    try:
                        src.tk.call(src_sb, *args)
                    except Exception:  # noqa: BLE001
                        pass
                src_drive(*args)

            def tgt_cmd(*args):
                if tgt_sb:
                    try:
                        tgt.tk.call(tgt_sb, *args)
                    except Exception:  # noqa: BLE001
                        pass
                tgt_drive(*args)

            src.configure(yscrollcommand=src_cmd)
            tgt.configure(yscrollcommand=tgt_cmd)
        except Exception:  # noqa: BLE001
            logutil.exc("setup sync scroll")

    def _textbox(self, parent) -> ctk.CTkTextbox:
        # low natural height on purpose — the pane grows by expand, so the
        # acronym strip below can always claim the height it asks for
        return ctk.CTkTextbox(
            parent,
            height=120,
            fg_color=T.FIELD,
            text_color=T.INK,
            border_width=1,
            border_color=T.LINE,
            border_spacing=T.TEXT_BORDER_SPACING,
            font=ui_font(T.FONT_BODY_SIZE),
            wrap="word",
            corner_radius=T.CORNER_SM,
            scrollbar_button_color=T.LINE,
            scrollbar_button_hover_color=T.LINE_STRONG,
        )

    def _combo_style(self) -> dict:
        return dict(
            fg_color=T.FIELD,
            border_color=T.LINE,
            button_color=T.LINE_STRONG,
            button_hover_color=T.INK_SOFT,
            text_color=T.INK,
            dropdown_fg_color=T.SURFACE,
            dropdown_text_color=T.INK,
            font=ui_font(12),
            corner_radius=T.CORNER_SM,
        )

    def _settings_btn(self, parent) -> ctk.CTkButton:
        # Segoe MDL2 gear — readable; old png looked like a snowflake
        return ctk.CTkButton(
            parent,
            text=T.GLYPH_SETTINGS,
            font=mdl2_font(15),
            width=40,
            height=T.ROW_H,
            corner_radius=T.ROW_H // 2,
            fg_color=T.SURFACE,
            border_width=1,
            border_color=T.LINE,
            hover_color=T.CHIP_HOVER,
            text_color=T.INK,
            command=self.open_settings,
        )

    # ── AI group ─────────────────────────────────────────────────────────
    # One fenced-off block so it can grey out as a unit: without ~/.bonjour-epta/
    # ai.json or without a live token there is nothing here that can work.

    AI_INNER_H = 22

    def _build_ai_group(self, parent) -> ctk.CTkFrame:
        # No pack_propagate(False) here: frozen, the frame would keep CTk's default
        # 200px while the children ask for ~232, and pack squeezes the last button
        # until its own label spills over the neighbour. Every child is a fixed
        # size, so letting the frame hug them gives the same ROW_H and always fits.
        self._ai_group = ctk.CTkFrame(
            parent,
            corner_radius=T.ROW_H // 2,
            fg_color=T.SURFACE,
            border_width=1,
            border_color=T.LINE,
        )

        h = self.AI_INNER_H
        pad = (T.ROW_H - h) // 2

        self._btn_token = ctk.CTkButton(
            self._ai_group,
            text=T.GLYPH_TOKEN,
            font=mdl2_font(12),
            width=28,
            height=h,
            corner_radius=h // 2,
            fg_color="transparent",
            hover_color=T.CHIP_HOVER,
            text_color=T.INK_SOFT,
            border_width=0,
            command=self.paste_ai_token,
        )
        self._btn_token.pack(side="left", padx=(3, 0), pady=pad)

        # heights pinned to the buttons' — a default-height label would make the
        # whole group taller than every other control in the toolbar
        self._token_dot = ctk.CTkLabel(
            self._ai_group,
            text="●",
            width=12,
            height=h,
            font=ui_font(11),
            text_color=T.INK_FAINT,
            anchor="center",
        )
        self._token_dot.pack(side="left", pady=pad)

        # fixed width — the group must not twitch every time a minute ticks off
        self._token_lbl = ctk.CTkLabel(
            self._ai_group,
            text="",
            width=28,
            height=h,
            font=ui_font(10),
            text_color=T.INK_FAINT,
            anchor="w",
        )
        self._token_lbl.pack(side="left", padx=(2, 0), pady=pad)

        # a floor, not the final size: CTkButton never renders narrower than its
        # own label plus padding, so the group ends up label-driven either way
        self._btn_polish = self._ai_btn(self._ai_title(1), self.polish_now, 64)
        self._btn_polish.pack(side="left", padx=(2, 0), pady=pad)
        self._btn_explain = self._ai_btn(self._ai_title(2), self.explain_now, 54)
        self._btn_explain.pack(side="left", padx=(2, 5), pady=pad)

        self._sync_ai_group()
        return self._ai_group

    AI_TITLE_MAX = 14  # clamp so a long/empty label never inflates the toolbar

    def _ai_title(self, n: int) -> str:
        t = (assistant.fn1_title() if n == 1 else assistant.fn2_title()).strip()
        if not t:
            t = assistant.DEFAULT_FN1_TITLE if n == 1 else assistant.DEFAULT_FN2_TITLE
        return t if len(t) <= self.AI_TITLE_MAX else t[: self.AI_TITLE_MAX - 1] + "…"

    def _ai_btn(self, text: str, cmd: Callable, w: int) -> ctk.CTkButton:
        return ctk.CTkButton(
            self._ai_group,
            text=text,
            width=w,
            height=self.AI_INNER_H,
            corner_radius=self.AI_INNER_H // 2,
            fg_color="transparent",
            hover_color=T.CHIP_HOVER,
            text_color=T.INK,
            border_width=0,
            font=ui_font(11),
            command=cmd,
        )

    def _ai_configured(self) -> bool:
        """The feature exists at all: switched on and the active backend is set up.

        Gateway needs ai.json; Gemini needs its encrypted key. This decides whether
        the AI group is interactive at all — the dot/minutes still come from the
        gateway token, which simply reads as absent on the Gemini backend.
        """
        try:
            if not cfg.get().ai_enabled:
                return False
            if getattr(cfg.get(), "ai_provider", "gateway") == "gemini":
                from . import ai_secrets

                return ai_secrets.available() and ai_secrets.has_key("gemini")
            return ai_config.configured()
        except Exception:  # noqa: BLE001
            return False

    def _sync_ai_group(self) -> None:
        """Repaint the dot, the minutes left, and whether the buttons can be pressed."""
        if not hasattr(self, "_ai_group"):
            return
        left = ai_token.seconds_left()

        if not self._ai_configured():
            dot, note = T.INK_FAINT, ""
        elif not ai_token.present():
            dot, note = T.INK_FAINT, "нет"
        elif left <= 0:
            dot, note = T.ERR, "истёк"
        elif left < 15 * 60:
            dot, note = T.WARN, f"{left // 60}м"
        else:
            dot, note = T.OK, f"{left // 60}м"

        usable = self._ai_configured() and left > 0
        state = "normal" if usable else "disabled"
        try:
            self._token_dot.configure(text_color=dot)
            self._token_lbl.configure(text=note)
            self._btn_token.configure(
                state="normal" if self._ai_configured() else "disabled"
            )
            self._btn_polish.configure(state=state, text=self._ai_title(1))
            self._btn_explain.configure(state=state, text=self._ai_title(2))
            # inert group sinks into the toolbar; live one lifts off it
            self._ai_group.configure(fg_color=T.SURFACE if usable else T.BG)
        except Exception:  # noqa: BLE001
            pass

    def _watch_token(self) -> None:
        """The label counts down on its own; the watcher thread only fires on changes."""
        self._sync_ai_group()
        try:
            self._token_after_id = self.after(30_000, self._watch_token)
        except Exception:  # noqa: BLE001
            self._token_after_id = None

    def _on_token_change(self) -> None:
        """Called from the renew thread — hop back onto Tk before touching widgets."""
        try:
            self.after(0, self._sync_ai_group)
        except Exception:  # noqa: BLE001
            pass

    def paste_ai_token(self) -> None:
        ok, msg = ai_token.paste_from_clipboard()
        self._sync_ai_group()
        self._flash_foot(("✓ " if ok else "") + msg, ok)

    def _flash_foot(self, text: str, ok: bool = True) -> None:
        """Say something in the footer for four seconds, then put the hotkey back."""

        def restore() -> None:
            # a theme switch in the meantime replaced the label we captured
            try:
                self._hk_foot.configure(text=self._hotkey_footer(), text_color=T.INK_FAINT)
            except Exception:  # noqa: BLE001
                pass

        try:
            self._hk_foot.configure(text=text, text_color=T.OK if ok else T.ERR)
            self.after(4000, restore)
        except Exception:  # noqa: BLE001
            pass

    def _ghost(self, parent, text: str, cmd: Callable, w: int = 88) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            width=w,
            height=T.ROW_H,
            corner_radius=T.ROW_H // 2,
            fg_color=T.SURFACE,
            border_width=1,
            border_color=T.LINE,
            hover_color=T.CHIP_HOVER,
            text_color=T.INK,
            font=ui_font(12),
            command=cmd,
        )

    def _clear_icon(self, parent, cmd: Callable) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text="✕",
            width=T.ICON_W,
            height=T.CTRL_H,
            corner_radius=T.CORNER_SM,
            fg_color=T.CLEAR_TINT,
            border_width=1,
            border_color=T.CLEAR_BORDER,
            hover_color=T.CLEAR_HOVER,
            text_color=T.ERR,
            font=ui_font(11),
            command=cmd,
        )

    def _icon(self, parent, text: str, cmd: Callable, w: int = 32) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent,
            text=text,
            width=w,
            height=T.CTRL_H,
            corner_radius=T.CORNER_SM,
            fg_color=T.CHIP_BG,
            border_width=1,
            border_color=T.LINE,
            hover_color=T.CHIP_HOVER,
            text_color=T.INK_SOFT,
            font=ui_font(11),
            command=cmd,
        )

    def open_settings(self) -> None:
        if self._settings_win is not None and self._settings_win.winfo_exists():
            self._settings_win.lift()
            return
        self._settings_win = SettingsWindow(self)

    def open_acro_window(self, term: str = "") -> None:
        """Dictionary window — from the strip's dictionary link, settings, or an unknown word."""
        from .acro_window import AcroWindow

        win = getattr(self, "_acro_win", None)
        if win is not None:
            try:
                if win.winfo_exists():
                    win.lift()
                    win.focus_set()
                    win.search_for(term)
                    return
            except Exception:  # noqa: BLE001
                pass
        self._acro_win = AcroWindow(self, term=term, on_changed=self._refresh_acronyms)

    def open_style_picker(self) -> None:
        from .style_picker import StylePickerWindow

        if getattr(self, "_style_win", None) is not None:
            try:
                if self._style_win.winfo_exists():
                    self._style_win.lift()
                    return
            except Exception:  # noqa: BLE001
                pass

        def saved(sid: int) -> None:
            cb = getattr(self, "on_chip_style_changed", None)
            if cb:
                try:
                    cb(sid)
                except Exception:  # noqa: BLE001
                    pass

        self._style_win = StylePickerWindow(self, on_saved=saved)

    def _on_settings_changed(self, s: cfg.AppSettings) -> None:
        def apply() -> None:
            theme = s.ui_theme if s.ui_theme in T.THEME_CHOICES else T.THEME_LIGHT
            if theme != getattr(self, "_theme_pref", None):
                self._theme_pref = theme
                self._restyle_theme(theme)
            self._provider.set(s.provider_id)
            label = next(
                (lb for pid, lb, _ in tr.list_providers() if pid == s.provider_id), None
            )
            if label:
                self._provider_combo.set(label)
            try:
                self._hk_foot.configure(text=self._hotkey_footer())
            except Exception:  # noqa: BLE001
                pass
            packs = s.acronym_packs if isinstance(s.acronym_packs, dict) else {}
            if packs != getattr(self, "_acro_packs", None):
                self._acro_packs = dict(packs)
                acronyms.set_enabled(packs)
            self._sync_ai_group()
            self._refresh_acronyms()

        try:
            self.after(0, apply)
        except Exception:  # noqa: BLE001
            apply()

    def _restyle_theme(self, preference: str) -> None:
        """Rebuild chrome so palette tokens stick after light/dark/auto switch."""
        # On Windows CTk repaints the titlebar by withdrawing and re-showing the
        # window, remembering whoever had focus and restoring it via after(1).
        # Everything it could remember is about to be destroyed below, so park
        # focus on the root first — the 100ms timer in _build takes it back.
        try:
            self.focus_set()
        except Exception:  # noqa: BLE001
            pass
        apply_theme(preference)
        src = ""
        tgt = ""
        try:
            src = self._src_box.get("1.0", "end-1c")
            tgt = self._tgt_box.get("1.0", "end-1c")
        except Exception:  # noqa: BLE001
            pass
        src_lang = self._source_lang.get()
        tgt_lang = self._target_lang.get()
        provider = self._provider.get()
        status = self._status.get()
        for child in list(self._shell.winfo_children()):
            try:
                child.destroy()
            except Exception:  # noqa: BLE001
                pass
        self.configure(fg_color=T.BG)
        self._shell.configure(fg_color=T.BG)
        self._build(self._shell)
        self._setup_sync_scroll()
        self._setup_spotlight()
        self._source_lang.set(src_lang)
        self._target_lang.set(tgt_lang)
        self._provider.set(provider)
        self._status.set(status)
        try:
            if src:
                self._src_box.insert("1.0", src)
            if tgt:
                self._tgt_box.insert("1.0", tgt)
        except Exception:  # noqa: BLE001
            pass
        label = next(
            (lb for pid, lb, _ in tr.list_providers() if pid == provider), None
        )
        if label:
            try:
                self._provider_combo.set(label)
            except Exception:  # noqa: BLE001
                pass
        try:
            self._src_combo.set(langs.label_of(src_lang))
            self._tgt_combo.set(langs.label_of(tgt_lang))
        except Exception:  # noqa: BLE001
            pass
        self._refresh_acronyms(src)

    def _on_provider_ui(self, label: str) -> None:
        pid = self._provider_map.get(label, tr.DEFAULT_PROVIDER_ID)
        self._provider.set(pid)
        cfg.update(provider_id=pid)
        self._set_provider_dot(None)  # unknown while probing
        self._probe_provider()

    def _set_provider_dot(self, ok: bool | None) -> None:
        """None=gray probing, True=green, False=red."""
        if not hasattr(self, "_provider_dot"):
            return
        if ok is True:
            self._provider_dot.configure(text_color=T.OK)
        elif ok is False:
            self._provider_dot.configure(text_color=T.ERR)
        else:
            self._provider_dot.configure(text_color=T.INK_FAINT)

    def _probe_provider(self) -> None:
        """Lightweight reachability check for selected provider (green/red dot)."""
        pid = self._provider.get()
        self._set_provider_dot(None)

        def work() -> None:
            ok = False
            try:
                # tiny probe — same path as real translate
                r = tr.translate("ok", source="en", target="ru", provider_id=pid)
                ok = bool(r.ok and (r.text or "").strip())
            except Exception:  # noqa: BLE001
                ok = False
            try:
                self.after(0, lambda: self._set_provider_dot(ok))
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=work, daemon=True).start()

    def _on_src_lang(self, label: str) -> None:
        code = self._src_label_to_code.get(label, "auto")
        self._source_lang.set(code)
        cfg.update(source_lang=code)

    def _on_tgt_lang(self, label: str) -> None:
        code = self._tgt_label_to_code.get(label, "ru")
        self._target_lang.set(code)
        cfg.update(target_lang=code)
        if cfg.get().instant_translate and self.get_source_text().strip():
            self.translate_now()

    # ── text IO — write through inner tk.Text (CTk wrapper can drop inserts) ──
    def _inner(self, box: ctk.CTkTextbox):
        return getattr(box, "_textbox", None) or box

    @staticmethod
    def _focus_if_alive(widget) -> None:
        """For focus scheduled with after(): the widget may be gone by the time it fires."""
        try:
            if widget.winfo_exists():
                widget.focus_set()
        except Exception:  # noqa: BLE001
            pass

    def set_source_text(self, text: str) -> None:
        from . import logutil
        from .selection import normalize_newlines, sanitize_selection

        text = sanitize_selection(text)
        log = logutil.get()
        log.debug("set_source_text len=%s head=%r", len(text), logutil.head(text))
        inner = self._inner(self._src_box)
        log.debug("inner type=%s", type(inner).__name__)
        try:
            inner.configure(state="normal")
        except Exception:  # noqa: BLE001
            logutil.exc("src configure normal")
        try:
            inner.delete("1.0", "end")
            if text:
                inner.insert("1.0", text)
                try:
                    inner.see("1.0")
                    inner.mark_set("insert", "end")
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            logutil.exc("src delete/insert")
        try:
            self._src_box.update_idletasks()
        except Exception:  # noqa: BLE001
            pass
        got = ""
        try:
            got = inner.get("1.0", "end-1c")
        except Exception:  # noqa: BLE001
            logutil.exc("src verify get")
        log.info(
            "set_source_text verify len_in=%s len_got=%s match=%s head_got=%r",
            len(text),
            len(got or ""),
            (got or "") == text,
            logutil.head(got, 80),
        )
        self._refresh_acronyms(got or "")

    def _refresh_acronyms(self, text: str | None = None) -> None:
        """Local dict lookup — runs on the UI thread, ahead of the translation."""
        panel = getattr(self, "_acro", None)
        if panel is None:
            return
        try:
            if not cfg.get().acronyms_enabled:
                panel.hide()
                return
            src = self.get_source_text() if text is None else text
            rep = acronyms.explain(src)
            panel.render(rep)
            if rep:
                logutil.get().debug(
                    "acronyms %s hits, %s unknown, %.2f ms",
                    rep.count,
                    len(rep.unknown),
                    rep.ms,
                )
        except Exception:  # noqa: BLE001
            logutil.exc("acronyms refresh")
            try:
                panel.hide()
            except Exception:  # noqa: BLE001
                pass

    def get_source_text(self) -> str:
        inner = self._inner(self._src_box)
        try:
            return inner.get("1.0", "end-1c")
        except Exception:  # noqa: BLE001
            return self._src_box.get("1.0", "end-1c")

    def set_target_text(self, text: str) -> None:
        text = normalize_newlines(text)
        inner = self._inner(self._tgt_box)
        try:
            inner.configure(state="normal")
        except Exception:  # noqa: BLE001
            pass
        inner.delete("1.0", "end")
        if text:
            inner.insert("1.0", text)

    def _cancel_progress_anim(self) -> None:
        self._tgt_progress = False
        if self._progress_after_id is not None:
            try:
                self.after_cancel(self._progress_after_id)
            except Exception:  # noqa: BLE001
                pass
            self._progress_after_id = None

    def _show_translate_progress(self, word: str = "переводим") -> None:
        """Clear stale translation and show calm loading state."""
        self._cancel_progress_anim()
        self._tgt_progress = True
        self._progress_word = word
        try:
            self._tgt_box.configure(text_color=T.INK_FAINT)
            self._tgt_pane.configure(border_color=T.INK_SOFT, border_width=2)
        except Exception:  # noqa: BLE001
            pass
        self.set_target_text(word)
        self._progress_tick = 0
        self._progress_anim()

    def _end_translate_progress_ui(self) -> None:
        try:
            self._tgt_box.configure(text_color=T.INK)
            self._tgt_pane.configure(border_color=T.LINE, border_width=1)
        except Exception:  # noqa: BLE001
            pass

    def _progress_anim(self) -> None:
        if not self._busy or not self._tgt_progress:
            return
        self._progress_tick = (self._progress_tick + 1) % 4
        dots = "." * self._progress_tick
        self.set_target_text(f"{self._progress_word}{dots}")
        try:
            self._progress_after_id = self.after(420, self._progress_anim)
        except Exception:  # noqa: BLE001
            pass

    def copy_source(self) -> None:
        t = self.get_source_text()
        if t:
            self._to_clipboard(t)

    def copy_target(self) -> None:
        t = self._inner(self._tgt_box).get("1.0", "end-1c")
        if t:
            self._to_clipboard(t)

    def clear_source(self) -> None:
        self.set_source_text("")

    def clear_target(self) -> None:
        self.set_target_text("")

    def clear_all(self) -> None:
        self._translate_job += 1
        self._ai_job += 1
        self._cancel_progress_anim()
        self._busy = False
        self._btn_translate.configure(state="normal")
        try:
            self._tgt_box.configure(text_color=T.INK)
        except Exception:  # noqa: BLE001
            pass
        self.clear_source()
        self.clear_target()
        self._ai_panel.hide()
        self._end_translate_progress_ui()
        self._sync_ai_group()

    # ── clipboard keys ────────────────────────────────────────────────────
    # Windows virtual key codes — layout independent. Tk reports keysym by the
    # *active* layout, so with a Cyrillic layout Ctrl+V arrives as
    # <Control-Cyrillic_em> and never matches <Control-v>: the class binding
    # runs instead (which just moves/extends the selection). Match on keycode.
    _VK_A, _VK_C, _VK_V, _VK_X = 65, 67, 86, 88

    def _bind_clipboard_keys(self, widget) -> None:
        """Layout-independent Ctrl+V/C/X/A + Shift+Insert on a tk.Text."""
        widget.bind("<<Paste>>", self._on_src_paste)
        widget.bind("<Shift-Insert>", self._on_src_paste)
        widget.bind("<Control-KeyPress>", self._on_ctrl_key)

    def _bind_copy_keys(self, widget) -> None:
        """Copy / cut / select-all only — Ctrl+V keeps Tk's own behaviour."""
        widget.bind("<Control-KeyPress>", self._on_ctrl_copy_key)

    def _on_ctrl_key(self, event):
        keycode = getattr(event, "keycode", 0)
        keysym = (getattr(event, "keysym", "") or "").lower()
        if keycode == self._VK_V or keysym in ("v", "cyrillic_em"):
            return self._on_src_paste(event)
        return self._on_ctrl_copy_key(event)

    def _on_ctrl_copy_key(self, event):
        keycode = getattr(event, "keycode", 0)
        keysym = (getattr(event, "keysym", "") or "").lower()
        if keycode == self._VK_C or keysym in ("c", "cyrillic_es"):
            return self._copy_selection(getattr(event, "widget", None))
        if keycode == self._VK_X or keysym in ("x", "cyrillic_che"):
            return self._copy_selection(getattr(event, "widget", None), cut=True)
        if keycode == self._VK_A or keysym in ("a", "cyrillic_ef"):
            return self._select_all(getattr(event, "widget", None))
        return None  # let every other Ctrl+key keep its default behaviour

    def _on_window_ctrl_key(self, event):
        """Fallback for Ctrl+V when focus is not in a text widget."""
        keycode = getattr(event, "keycode", 0)
        keysym = (getattr(event, "keysym", "") or "").lower()
        if keycode != self._VK_V and keysym not in ("v", "cyrillic_em"):
            return None
        try:
            focused = self.focus_get()
        except Exception:  # noqa: BLE001
            focused = None
        import tkinter as tk

        if isinstance(focused, (tk.Text, tk.Entry)):
            return None  # the widget binding already handled it
        try:
            self._inner(self._src_box).focus_set()
        except Exception:  # noqa: BLE001
            pass
        return self._on_src_paste(event)

    def _read_clipboard(self) -> str:
        """Clipboard text, with a Win32 fallback (Tk can fail on CF_UNICODETEXT)."""
        for kwargs in ({}, {"type": "UTF8_STRING"}, {"type": "STRING"}):
            try:
                text = self.clipboard_get(**kwargs)
                if text:
                    return text
            except Exception:  # noqa: BLE001
                pass
        try:
            text = pyperclip.paste()
            if text:
                return text
        except Exception:  # noqa: BLE001
            pass
        try:
            import ctypes

            u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
            CF_UNICODETEXT = 13
            if not u32.OpenClipboard(0):
                return ""
            try:
                handle = u32.GetClipboardData(CF_UNICODETEXT)
                if not handle:
                    return ""
                ptr = k32.GlobalLock(handle)
                if not ptr:
                    return ""
                try:
                    return ctypes.c_wchar_p(ptr).value or ""
                finally:
                    k32.GlobalUnlock(handle)
            finally:
                u32.CloseClipboard()
        except Exception:  # noqa: BLE001
            return ""

    def _on_src_paste(self, _e=None):
        """Handle Ctrl+V: paste clipboard into source box, then maybe auto-translate."""
        try:
            inner = self._inner(self._src_box)
            text = self._read_clipboard()
            if text:
                try:
                    if inner.tag_ranges("sel"):
                        inner.delete("sel.first", "sel.last")
                except Exception:  # noqa: BLE001
                    pass
                inner.insert("insert", text)
                inner.see("insert")
        except Exception:  # noqa: BLE001
            logutil.exc("src paste")
        self.after(50, self._after_edit)
        return "break"  # prevent double-paste from default handler

    def _text_widget(self, widget):
        """The tk.Text the key landed in — the source box when in doubt."""
        if widget is not None and hasattr(widget, "tag_ranges"):
            return widget
        return self._inner(self._src_box)

    def _to_clipboard(self, text: str) -> None:
        """pyperclip, not Tk.

        clipboard_append leaves Tk as the clipboard *owner* with delayed
        rendering: the text is served from this process on demand. Bonjour
        hides to tray and the window can be withdrawn or gone by the time the
        user pastes — then the paste arrives empty. pyperclip hands Windows a
        real memory block and walks away.
        """
        try:
            pyperclip.copy(text)
            return
        except Exception:  # noqa: BLE001
            logutil.exc("clipboard copy")
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:  # noqa: BLE001
            pass

    def _copy_selection(self, widget=None, *, cut: bool = False):
        inner = self._text_widget(widget)
        try:
            if not inner.tag_ranges("sel"):
                return "break"
            text = inner.get("sel.first", "sel.last")
            if text:
                self._to_clipboard(text)
            if cut:
                inner.delete("sel.first", "sel.last")
                if inner is self._inner(self._src_box):
                    self.after(50, self._after_edit)
        except Exception:  # noqa: BLE001
            logutil.exc("copy selection")
        return "break"

    def _select_all(self, widget=None):
        inner = self._text_widget(widget)
        try:
            inner.tag_add("sel", "1.0", "end-1c")
            inner.mark_set("insert", "1.0")
        except Exception:  # noqa: BLE001
            logutil.exc("select all")
        return "break"

    def _maybe_instant(self) -> None:
        if cfg.get().instant_translate and self.get_source_text().strip():
            self.translate_now()

    def _after_edit(self) -> None:
        """Paste: acronyms are local, so they show even when instant is off."""
        self._refresh_acronyms()
        self._maybe_instant()

    def swap_direction(self) -> None:
        src_text = self.get_source_text()
        tgt_text = self._inner(self._tgt_box).get("1.0", "end-1c")
        src_code = self._source_lang.get()
        tgt_code = self._target_lang.get()
        self.set_source_text(tgt_text)
        self.set_target_text(src_text)
        new_src = tgt_code
        new_tgt = src_code if src_code != "auto" else "en"
        self._source_lang.set(new_src)
        self._target_lang.set(new_tgt)
        self._src_combo.set(langs.label_of(new_src))
        self._tgt_combo.set(langs.label_of(new_tgt))
        cfg.update(source_lang=new_src, target_lang=new_tgt)
        if cfg.get().instant_translate and self.get_source_text().strip():
            self.translate_now()

    def _set_lang(self, which: str, code: str) -> None:
        """Move a combo + settings together — used by the auto-pick below."""
        if which == "source":
            self._source_lang.set(code)
            self._src_combo.set(langs.label_of(code))
            cfg.update(source_lang=code)
        else:
            self._target_lang.set(code)
            self._tgt_combo.set(langs.label_of(code))
            cfg.update(target_lang=code)

    def _autopick_langs(self, text: str) -> tuple[str, str]:
        """Aim the pair at the text — a wrong direction just returns it unchanged.

        Two everyday cases: an explicit ru→en pair fed English (translate it the
        other way), and a source language the text plainly is not written in.
        """
        source = self._source_lang.get()
        target = self._target_lang.get()

        want = langs.effective_target(target, source, text)
        if want and want != target:
            self._set_lang("source", target)
            self._set_lang("target", want)
            return target, want

        if langs.script_mismatch(source, text):
            source = "auto"
            self._set_lang("source", source)

        if source != "auto" and source == target:
            target = langs.counterpart(source)
            self._set_lang("target", target)
        return source, target

    def translate_now(self, *, _retry: bool = False) -> None:
        text = self.get_source_text().strip()
        if not text:
            return
        self._translate_job += 1
        job = self._translate_job
        self._busy = True
        self._btn_translate.configure(state="disabled")
        # Watchdog: providers time out at ~14s, so if _busy is still set at 30s
        # the result was lost somewhere — free the button rather than strand it.
        self._arm_busy_watchdog(job)
        try:
            # Anything here runs BEFORE the worker starts; if it throws, the
            # thread never launches and _busy would stay set forever (the
            # provider-switch lockup). Reset synchronously on any failure.
            self._refresh_acronyms(text)  # local — lands before the network answers
            self._show_translate_progress()
            source, target = self._autopick_langs(text)
            provider_id = self._provider.get()
        except Exception as exc:  # noqa: BLE001
            logutil.exc("translate_now setup")
            self._busy = False
            self._btn_translate.configure(state="normal")
            self._cancel_progress_anim()
            self._end_translate_progress_ui()
            self._flash_foot(f"не переведено: {exc}", False)
            return

        def work() -> None:
            # Never let an exception strand _busy: a dead thread used to leave the
            # translate button disabled and the progress frame up forever.
            try:
                result = tr.translate(text, source=source, target=target, provider_id=provider_id)
            except Exception as exc:  # noqa: BLE001
                logutil.exc("translate thread")
                result = tr.TranslateResult(text="", provider=provider_id or "", error=str(exc))
            self.after(0, lambda: self._apply_result(result, job, _retry))

        threading.Thread(target=work, daemon=True).start()

    def _arm_busy_watchdog(self, job: int, timeout_ms: int = 30_000) -> None:
        def check() -> None:
            # Only free the button if THIS job never landed — a newer translate
            # owns _busy now and must not be cancelled by an old watchdog.
            if self._busy and job == self._translate_job:
                logutil.get().warning("translate watchdog fired job=%s — freeing _busy", job)
                self._cancel_progress_anim()
                self._busy = False
                self._btn_translate.configure(state="normal")
                self._end_translate_progress_ui()
                self._flash_foot("перевод не ответил вовремя", False)
        try:
            self.after(timeout_ms, check)
        except Exception:  # noqa: BLE001
            pass

    def _adopt_detected(self, result: TranslateResult, retried: bool) -> bool:
        """Learn the real language from the answer and re-aim if it hit the target.

        Asked to turn Russian into Russian, every provider echoes the text back,
        which the user reads as a broken translator. True = a retry is on its way.
        """
        det = (result.detected_source or "").lower().split("-")[0]
        if not det or det not in langs.LANG_LABELS:
            return False
        if det != self._target_lang.get() or retried:
            return False
        self._set_lang("target", langs.counterpart(det))
        self.translate_now(_retry=True)
        return True

    def _apply_result(self, result: TranslateResult, job: int, retried: bool = False) -> None:
        if job != self._translate_job:
            return
        self._cancel_progress_anim()
        self._busy = False
        self._btn_translate.configure(state="normal")
        self._end_translate_progress_ui()
        if not result.ok:
            self._hk_foot.configure(text_color=T.ERR)
            self.set_target_text("")
            self.after(4000, lambda: self._hk_foot.configure(text_color=T.INK_FAINT))
            return
        self._hk_foot.configure(text_color=T.INK_FAINT)
        if self._adopt_detected(result, retried):
            return
        self.set_target_text(result.text)

    # ── AI actions ────────────────────────────────────────────────────────

    def _ai_start(self, *, cancels_translate: bool = True) -> bool:
        """Common gate: refuse politely, then lock the toolbar for one request.

        cancels_translate=True (polish, which writes the target pane) invalidates
        any in-flight translation so its result cannot land under the AI output.
        explain() passes False: it lands in the AI strip below the panes and must
        NOT cancel a translation the user is still waiting for (the chivoblya
        flow runs translate + explain together; bumping the job killed the
        translate and left "переводим" spinning forever).
        """
        if not self._ai_configured():
            self._flash_foot("ИИ выключен — нет ai.json", False)
            return False
        ok, why = ai_client.available()
        if not ok:
            self._flash_foot(why, False)
            self._sync_ai_group()
            return False
        if cancels_translate:
            self._translate_job += 1  # a translation in flight must not land on top
        self._ai_job += 1
        self._busy = True
        self._btn_translate.configure(state="disabled")
        self._btn_polish.configure(state="disabled")
        self._btn_explain.configure(state="disabled")
        return True

    def _ai_done(self) -> None:
        self._cancel_progress_anim()
        self._busy = False
        self._btn_translate.configure(state="normal")
        self._end_translate_progress_ui()
        self._sync_ai_group()

    def _ai_failed(self, msg: str, job: int, clear: bool = False) -> None:
        if job != self._ai_job:
            return
        self._ai_done()
        if clear:
            self.set_target_text("")
        self._ai_panel.show_error(msg)
        self._flash_foot(msg, False)

    def _ai_thread(self, call: Callable, land: Callable, job: int, clear: bool) -> None:
        def work() -> None:
            try:
                out = call()
            except ai_client.AiError as exc:
                msg = str(exc)
                self.after(0, lambda: self._ai_failed(msg, job, clear))
                return
            except Exception:  # noqa: BLE001
                logutil.exc("ai request")
                self.after(0, lambda: self._ai_failed("не получилось", job, clear))
                return
            self.after(0, lambda: land(out))

        threading.Thread(target=work, daemon=True).start()

    def polish_now(self) -> None:
        """Rough Russian on the left → clean English on the right, reasons below."""
        text = self.get_source_text().strip()
        if not text or not self._ai_start():
            return
        job = self._ai_job
        self._show_translate_progress("причесываем")
        self._ai_panel.hide()
        self._ai_thread(
            lambda: assistant.polish(text),
            lambda p: self._apply_polish(p, job),
            job,
            clear=True,
        )

    def _apply_polish(self, p, job: int) -> None:
        if job != self._ai_job:
            return
        self._ai_done()
        self.set_target_text(p.english)
        self._ai_panel.show_polish(p.russian, p.why)

    def explain_now(self) -> None:
        """What the phrase actually means — the target pane stays untouched."""
        text = self.get_source_text().strip()
        if not text or not self._ai_start(cancels_translate=False):
            return
        job = self._ai_job
        self._ai_panel.show_wait("разбираемся…")
        self._ai_thread(
            lambda: assistant.explain_phrase(text),
            lambda answer: self._apply_explain(answer, job),
            job,
            clear=False,
        )

    def _apply_explain(self, answer: str, job: int) -> None:
        if job != self._ai_job:
            return
        self._ai_done()
        self._ai_panel.show_text("ИИ · объяснил", answer)

    def bring_with_selection(self, text: str) -> None:
        """Fill source on UI thread. Chip click is already on main thread → run now."""
        import threading

        from . import logutil
        from .selection import normalize_newlines, sanitize_selection

        text = sanitize_selection(text)
        log = logutil.get()
        log.info(
            "bring_with_selection called len=%s head=%r thread=%s",
            len(text),
            logutil.head(text),
            threading.current_thread().name,
        )

        def ui() -> None:
            log.debug("bring ui() enter")
            try:
                self.deiconify()
                self.lift()
            except Exception:  # noqa: BLE001
                logutil.exc("deiconify/lift")
            if not text:
                log.warning("bring ui: empty text")
                return
            self.clear_target()
            self.set_source_text(text)
            got = self.get_source_text().strip()
            if got != text:
                log.warning("bring mismatch, retry insert")
                try:
                    inn = self._inner(self._src_box)
                    inn.delete("1.0", "end")
                    inn.insert("1.0", text)
                except Exception:  # noqa: BLE001
                    logutil.exc("bring retry insert")
                got = self.get_source_text().strip()
            try:
                self.attributes("-topmost", True)
                self.after(120, lambda: self.attributes("-topmost", False))
            except Exception:  # noqa: BLE001
                pass
            try:
                self.focus_force()
                self._inner(self._src_box).focus_set()
            except Exception:  # noqa: BLE001
                pass
            ok = bool(got)
            log.info("bring done ok=%s len=%s head=%r", ok, len(got), logutil.head(got, 80))
            if ok and cfg.get().instant_translate:
                log.debug("instant translate after bring")
                self.translate_now()

        # Chip/Button click already on Tk main thread — after(0) can be delayed
        # forever if the event queue is wedged; run immediately when possible.
        try:
            main = threading.main_thread()
            if threading.current_thread() is main:
                log.debug("bring run direct (main thread)")
                ui()
                return
        except Exception:  # noqa: BLE001
            pass
        try:
            self.after(0, ui)
            log.debug("bring scheduled via after(0)")
        except Exception:  # noqa: BLE001
            logutil.exc("after(0) failed, run ui direct")
            ui()

    def _auto_check_updates(self) -> None:
        """Daily background check. Silent unless there is something to install."""
        import time

        from . import updater

        try:
            if updater.due(cfg.get().update_last_check, time.time()):
                self._check_updates(manual=False)
        except Exception:  # noqa: BLE001
            logutil.exc("auto update check")
        finally:
            # Re-arm regardless: a machine left running for a week must keep looking.
            self.after(AUTO_CHECK_EVERY_MS, self._auto_check_updates)

    def _check_updates(self, manual: bool = True) -> None:
        """Title-bar ↻ — ask the public feed, then offer the update."""
        from . import updater

        if getattr(self, "_update_busy", False):
            return
        self._update_busy = True
        if manual:
            self._flash_foot("проверяю обновления…", True)

        # Tk's after() is NOT safe to call from a worker thread — on Windows it
        # can silently fail to queue, and the result never lands. Park the answer
        # in a slot and let a poller that lives on the UI thread pick it up.
        self._update_result = None
        self._update_done = False

        def work() -> None:
            try:
                info = updater.fetch_manifest()
            except Exception:  # noqa: BLE001
                info = None
            self._update_result = info
            self._update_done = True

        threading.Thread(target=work, daemon=True, name="update-check").start()
        self._poll_update_result(manual, 0)

    def _poll_update_result(self, manual: bool, tries: int) -> None:
        """Runs on the UI thread: waits for the worker, then reports the verdict."""
        if getattr(self, "_update_done", False):
            info = getattr(self, "_update_result", None)
            self._update_result = None
            self._update_done = False
            self._on_update_checked(info, manual)
            return
        if tries > 300:  # ~30s — give up and free the button
            self._update_busy = False
            if manual:
                self._flash_foot("проверка обновлений не ответила", False)
            return
        try:
            self.after(100, lambda: self._poll_update_result(manual, tries + 1))
        except Exception:  # noqa: BLE001
            self._update_busy = False

    def _update_busy_watchdog(self) -> None:
        """Reset a stuck _update_busy if a check clearly did not finish."""
        try:
            if getattr(self, "_update_busy", False):
                self._update_busy = False
        except Exception:  # noqa: BLE001
            pass

    def _on_update_checked(self, info: dict | None, manual: bool = True) -> None:
        import time

        from . import updater
        from .update_ui import ask

        self._update_busy = False
        verdict = updater.decide(APP_VERSION, info, cfg.get().update_skip_version)
        if verdict != updater.BAD_MANIFEST:
            # Only a check that actually reached the feed resets the daily clock;
            # a flaky network must not buy silence for another 24 hours.
            cfg.update(update_last_check=time.time())
        if verdict == updater.BAD_MANIFEST:
            if manual:
                # A button press deserves a window, not a flash the user may miss.
                from .update_ui import show_message

                show_message(
                    self,
                    "Не удалось проверить обновления",
                    "Не получилось связаться с сервером обновлений.\n"
                    "Проверьте подключение к сети и попробуйте позже.",
                )
            return
        if verdict == updater.UP_TO_DATE:
            if manual:
                from .update_ui import show_message

                show_message(
                    self,
                    "Обновлений нет",
                    f"У вас установлена последняя версия — {APP_VERSION}.\n"
                    "Всё в порядке, ничего делать не нужно.",
                )
            return
        if verdict == updater.DISMISSED:
            # Skipped version: stay quiet in the background, but a button press
            # is the user asking — show it again.
            if not manual:
                return
            cfg.update(update_skip_version="")

        choice, skip = ask(self, info, APP_VERSION)
        if choice != "update":
            if skip:
                cfg.update(update_skip_version=info["version"])
            self._set_status_safe("")
            return

        self._flash_foot("скачиваю обновление…", True)
        self.update_idletasks()
        if not updater.apply(info):
            self._flash_foot("не удалось обновиться — попробуйте позже", False)
            return
        self._hard_exit()

    def _set_status_safe(self, text: str) -> None:
        try:
            self._status.set(text)
        except Exception:  # noqa: BLE001
            pass

    def _hard_exit(self) -> None:
        """Stop tray / destroy best-effort, then hard-exit so the mutex drops.

        after() is useless here — destroy ends mainloop; os._exit is immediate.
        """
        import os

        tray = getattr(self, "_tray", None)
        if tray is not None:
            try:
                tray.stop()
            except Exception:  # noqa: BLE001
                pass
        try:
            self.destroy()
        except Exception:  # noqa: BLE001
            pass
        os._exit(0)

    def _restart_client(self) -> None:
        """Full process kill + fresh start (tray menu / dev reload)."""
        log = logutil.get()
        log.info("restart client requested")
        try:
            self._status.set("перезапуск…")
        except Exception:  # noqa: BLE001
            pass
        ok = False
        try:
            ok = schedule_relaunch()
        except Exception:  # noqa: BLE001
            logutil.exc("schedule_relaunch")
        if not ok:
            try:
                self._status.set("не удалось перезапустить")
            except Exception:  # noqa: BLE001
                pass
            return
        self._hard_exit()

    def _on_close(self, force: bool = False) -> None:
        """Window X / Alt+F4: hide to tray when enabled. force=True = real quit."""
        if not force and cfg.get().close_to_tray:
            self._minimize_to_tray()
            return
        tray = getattr(self, "_tray", None)
        if tray is not None:
            try:
                tray.stop()
            except Exception:  # noqa: BLE001
                pass
        self.destroy()


def run_app() -> TranslatorApp:
    return TranslatorApp()
