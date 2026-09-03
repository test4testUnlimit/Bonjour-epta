"""Settings — live apply; interactive hotkey capture. Tabs, no vertical scroll."""

from __future__ import annotations

import sys

import customtkinter as ctk

from . import settings as cfg
from . import theme as T
from . import translators as tr
from .autostart import sync as sync_autostart
from .screen import center_on_screen, work_area
from .theme import ui_font
from .ui_widgets import tune_combobox
from .app_icon import apply as apply_app_icon
from .win_hotkeys import HotkeySpec, check_reserved

try:
    import keyboard
except ImportError:  # pragma: no cover
    keyboard = None  # type: ignore

_MODE_DOUBLE = "×2 одна клавиша"
_MODE_COMBO = "комбинация"

# Logical (pre-DPI) geometry for a horizontal, tabbed settings window.
_WIN_W = 620
# 560 was not enough for the "основные" tab: pack ran out of room and crushed the
# last rows (the dump showed «записать…» at h=12 instead of 37). Give the window
# the height the tallest tab actually needs.
_WIN_H = 720


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, master: ctk.CTk) -> None:
        super().__init__(master)
        self.title(T.APP_NAME)
        self.geometry(f"{_WIN_W}x{_WIN_H}+-9999+-9999")
        self.minsize(560, 620)
        self.configure(fg_color=T.SETTINGS_BG)
        self.resizable(True, True)
        self.transient(master)
        self.after(0, lambda: apply_app_icon(self))

        self._capture_hook = None
        self._pending: HotkeySpec | None = None
        s = cfg.get()
        self._hk = s.hotkey_spec()
        self._mode_btns: dict[str, ctk.CTkButton] = {}
        self._theme_btns: dict[str, ctk.CTkButton] = {}
        self._ui_theme = s.ui_theme if s.ui_theme in T.THEME_CHOICES else T.THEME_LIGHT

        pad = T.PAD + 2
        ctk.CTkLabel(
            self, text="настройки", font=ui_font(17, "bold"), text_color=T.INK
        ).pack(anchor="w", padx=pad, pady=(8, 4))

        # One text colour can never read on BOTH a near-black ACCENT and a
        # near-white SURFACE (the contrast ratios mirror each other, so the
        # worst case is always ~1:1). So the selected tab is marked by an ACCENT
        # BORDER on the neutral SURFACE fill instead of a solid accent fill —
        # the browser-tab pattern. Text stays INK everywhere and keeps its
        # ~14-18:1 contrast on the surface in both themes.
        tabs = ctk.CTkTabview(
            self,
            fg_color=T.SETTINGS_CARD,
            corner_radius=T.CORNER,
            border_width=1,
            border_color=T.LINE,
            segmented_button_fg_color=T.SURFACE,
            segmented_button_selected_color=T.CHIP_HOVER,
            segmented_button_selected_hover_color=T.CHIP_HOVER,
            segmented_button_unselected_color=T.SURFACE,
            segmented_button_unselected_hover_color=T.CHIP_HOVER,
            text_color=T.INK,
            anchor="nw",
        )
        # NOTE: packed AFTER the footer below (see _pack_body) so the footer
        # claims its full height first; expand=True here would otherwise eat
        # everything and squeeze the close button to a few pixels.
        self._tabs_widget = tabs
        for name in ("основные", "акронимы", "ИИ"):
            tabs.add(name)
        self._tabs = tabs
        self._style_tab_buttons()

        self._build_general(tabs.tab("основные"), s)
        self._build_acronyms(tabs.tab("акронимы"))
        self._build_ai(tabs.tab("ИИ"))

        # No fixed height and no pack_propagate(False): with DPI scaling a frame
        # pinned to logical ROW_H+8 is SHORTER than the scaled button, and pack
        # squeezes the button (the dump showed h=12 instead of 37). Letting the
        # frame hug its children keeps every button at the same ROW_H everywhere.
        # Footer FIRST, anchored to the bottom: pack gives space in call order,
        # so the row that must keep its natural height has to be packed before
        # the greedy expand=True body. (Dump showed the button crushed to 12px.)
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(side="bottom", fill="x", padx=pad, pady=(0, 6))
        self._status = ctk.CTkLabel(foot, text="", text_color=T.INK_FAINT, font=ui_font(10))
        self._status.pack(side="left", pady=4)
        ctk.CTkButton(
            foot, text="закрыть", width=96, height=T.ROW_H,
            corner_radius=T.ROW_H // 2, fg_color=T.ACCENT,
            hover_color=T.ACCENT_HOVER, text_color=T.ON_ACCENT,
            font=ui_font(12), command=self._close,
        ).pack(side="right", pady=4)

        # now the body takes whatever is left
        self._tabs_widget.pack(fill="both", expand=True, padx=pad, pady=(0, 6))

        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after_idle(self._show_centered)

    def _show_centered(self) -> None:
        # CTk withdraws a Toplevel while it re-applies the titlebar/icon, so any
        # deiconify before that is undone. Do all geometry first, then deiconify
        # LAST — that is the only ordering that reliably leaves the window shown.
        try:
            self.update_idletasks()
        except Exception:
            return
        # Centre on the DISPLAY, not over the parent: the app itself normally
        # sits in the middle, so a parent-relative offset just looks crooked.
        center_on_screen(self)
        try:
            self.update_idletasks()
        except Exception:
            pass
        self.deiconify()
        self.lift()
        self.focus_force()
        # CTk re-applies the titlebar/icon on its own after() and WITHDRAWS the
        # window again when it does. Re-assert visibility once that settles.
        self.after(60, self._ensure_shown)

    def _ensure_shown(self) -> None:
        try:
            if str(self.state()) == "withdrawn":
                self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:  # noqa: BLE001
            pass

    def _style_tab_buttons(self) -> None:
        """Give the SELECTED tab an ACCENT border so it stands out on the neutral
        fill — the text colour stays readable (INK) on every tab."""
        try:
            sb = self._tabs._segmented_button
            buttons = getattr(sb, "_buttons_dict", {})
            current = self._tabs.get()
            for name, btn in buttons.items():
                selected = name == current
                btn.configure(
                    border_width=2 if selected else 0,
                    border_color=T.ACCENT if selected else T.LINE,
                    text_color=T.INK,
                )
            # Re-style on every switch via the TAB VIEW's own `command`, which
            # CTk calls AFTER it has switched the tab — never touch the segmented
            # button's command (that one does the switching; overriding it is
            # exactly what made the tabs stop responding).
            if not getattr(self._tabs, "_bonjur_styled_cmd", False):
                self._tabs.configure(command=self._style_tab_buttons)
                self._tabs._bonjur_styled_cmd = True
        except Exception:  # noqa: BLE001
            pass

    def _center_on_parent(self) -> None:
        try:
            self.update_idletasks()
            ww = int(self.winfo_width())
            wh = int(self.winfo_height())
            wx, wy, aw, ah = work_area()
            master = self.master
            use_parent = False
            if master is not None:
                try:
                    mw = int(master.winfo_width())
                    mh = int(master.winfo_height())
                    if mw > 1 and mh > 1 and str(master.state()) != "withdrawn":
                        mx = int(master.winfo_rootx())
                        my = int(master.winfo_rooty())
                        x = mx + (mw - ww) // 2
                        y = my + (mh - wh) // 2
                        use_parent = True
                except Exception:
                    pass
            if not use_parent:
                x = wx + (aw - ww) // 2
                y = wy + (ah - wh) // 2
            x = max(wx, min(x, wx + aw - ww))
            y = max(wy, min(y, wy + ah - wh))
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

    # ── shared switch style ───────────────────────────────────────────────
    def _switch_kw(self, command) -> dict:
        return dict(
            text_color=T.INK, font=ui_font(12), progress_color=T.SWITCH_ON,
            button_color=T.SWITCH_KNOB, button_hover_color=T.SWITCH_KNOB_HOVER,
            fg_color=T.SWITCH_OFF, command=command,
        )

    # ── tab: general ──────────────────────────────────────────────────────
    def _build_general(self, card, s) -> None:
        inner_pad = T.INSET
        switch_kw = self._switch_kw(self._apply_switches)

        self._instant = ctk.CTkSwitch(card, text="мгновенный перевод при вставке", **switch_kw)
        self._instant.pack(anchor="w", padx=inner_pad, pady=(inner_pad, 4))
        if s.instant_translate:
            self._instant.select()

        self._chivo = ctk.CTkSwitch(card, text="чивобля? при выделении текста", **switch_kw)
        self._chivo.pack(anchor="w", padx=inner_pad, pady=4)
        if s.chivoblya_enabled:
            self._chivo.select()

        self._autostart = ctk.CTkSwitch(card, text="запускать вместе с Windows", **switch_kw)
        self._autostart.pack(anchor="w", padx=inner_pad, pady=(0, 4))
        if s.autostart:
            self._autostart.select()
        if sys.platform != "win32":
            self._autostart.configure(state="disabled")

        self._close_tray = ctk.CTkSwitch(card, text="закрытие окна — в трей", **switch_kw)
        self._close_tray.pack(anchor="w", padx=inner_pad, pady=(0, 4))
        if s.close_to_tray:
            self._close_tray.select()

        self._sync_scroll = ctk.CTkSwitch(
            card, text="синхронная прокрутка обоих окон", **switch_kw
        )
        self._sync_scroll.pack(anchor="w", padx=inner_pad, pady=(0, 4))
        if s.sync_scroll:
            self._sync_scroll.select()

        self._spotlight = ctk.CTkSwitch(
            card, text="подсветка перевода выделенного фрагмента", **switch_kw
        )
        self._spotlight.pack(anchor="w", padx=inner_pad, pady=(0, 4))
        if s.spotlight:
            self._spotlight.select()

        trow = ctk.CTkFrame(card, fg_color="transparent")
        trow.pack(fill="x", padx=inner_pad, pady=(6, 2))
        ctk.CTkLabel(trow, text="тема", text_color=T.INK_FAINT, font=ui_font(11)).pack(anchor="w")
        theme_row = ctk.CTkFrame(trow, fg_color="transparent")
        theme_row.pack(anchor="w", pady=(4, 0))
        for i, key in enumerate(T.THEME_CHOICES):
            self._theme_btns[key] = self._theme_btn(
                theme_row, key, T.THEME_LABELS[key], side="left",
                padx=(0, 8) if i < len(T.THEME_CHOICES) - 1 else (0, 0),
            )
        self._sync_theme_buttons()

        prow = ctk.CTkFrame(card, fg_color="transparent")
        prow.pack(fill="x", padx=inner_pad, pady=(6, 2))
        ctk.CTkLabel(prow, text="провайдер", text_color=T.INK_FAINT, font=ui_font(11)).pack(anchor="w")
        labels = [label for _, label, _ in tr.list_providers()]
        self._pmap = {label: pid for pid, label, _ in tr.list_providers()}
        self._pinv = {pid: label for pid, label, _ in tr.list_providers()}
        self._prov = ctk.CTkComboBox(
            prow, values=labels, width=220, height=T.CTRL_H,
            command=lambda _v: self._apply_switches(),
            fg_color=T.FIELD, border_color=T.LINE, button_color=T.LINE_STRONG,
            button_hover_color=T.INK_SOFT, text_color=T.INK,
            dropdown_fg_color=T.SURFACE, dropdown_text_color=T.INK, font=ui_font(12),
        )
        self._prov.set(self._pinv.get(s.provider_id, labels[0]))
        self._prov.pack(anchor="w", pady=(3, 0))
        tune_combobox(self._prov)

        ctk.CTkFrame(card, fg_color=T.LINE, height=1).pack(fill="x", padx=inner_pad, pady=8)

        ctk.CTkLabel(
            card, text="горячая клавиша перевода", text_color=T.INK, font=ui_font(12, "bold")
        ).pack(anchor="w", padx=inner_pad)

        mode_row = ctk.CTkFrame(card, fg_color="transparent")
        mode_row.pack(anchor="w", padx=inner_pad, pady=(6, 4))
        self._mode_btns[_MODE_DOUBLE] = self._mode_btn(mode_row, _MODE_DOUBLE, side="left", padx=(0, 8))
        self._mode_btns[_MODE_COMBO] = self._mode_btn(mode_row, _MODE_COMBO, side="left")
        self._sync_mode_buttons()

        self._hk_label = ctk.CTkLabel(
            card, text=self._hk.label(), text_color=T.INK, font=ui_font(14, "bold")
        )
        self._hk_label.pack(anchor="w", padx=inner_pad, pady=(0, 2))

        self._hk_hint = ctk.CTkLabel(
            card, text=" ", text_color=T.INK_FAINT, font=ui_font(10),
            wraplength=460, justify="left", height=16,
        )
        self._hk_hint.pack(anchor="w", padx=inner_pad, pady=(0, 2))

        brow = ctk.CTkFrame(card, fg_color="transparent")
        brow.pack(fill="x", padx=inner_pad, pady=(0, inner_pad))
        self._btn_rec = ctk.CTkButton(
            brow, text="записать…", width=112, height=T.ROW_H,
            corner_radius=T.ROW_H // 2, fg_color=T.ACCENT,
            hover_color=T.ACCENT_HOVER, text_color=T.ON_ACCENT,
            font=ui_font(12), command=self._start_capture,
        )
        self._btn_rec.pack(side="left")
        ctk.CTkButton(
            brow, text="сброс Ctrl+Alt+E", width=128, height=T.ROW_H,
            corner_radius=T.ROW_H // 2, fg_color=T.SURFACE, border_width=1,
            border_color=T.LINE, hover_color=T.CHIP_HOVER, text_color=T.INK,
            font=ui_font(11), command=self._reset_hotkey,
        ).pack(side="left", padx=(8, 0))

    # ── tab: acronyms ─────────────────────────────────────────────────────
    def _build_acronyms(self, card) -> None:
        from . import acronyms

        inner_pad = T.INSET
        head = ctk.CTkFrame(card, fg_color="transparent", height=T.BAR_H)
        head.pack(fill="x", padx=inner_pad, pady=(inner_pad, 0))
        head.pack_propagate(False)
        ctk.CTkLabel(head, text="акронимы", text_color=T.INK, font=ui_font(12, "bold")).pack(side="left")
        btn_kw = dict(
            height=T.CTRL_H, corner_radius=T.CORNER_SM, fg_color=T.SURFACE,
            border_width=1, border_color=T.LINE, hover_color=T.CHIP_HOVER,
            text_color=T.INK_SOFT, font=ui_font(11),
        )
        ctk.CTkButton(head, text="папка паков", width=96, command=self._open_packs_dir, **btn_kw).pack(side="right")
        ctk.CTkButton(head, text="словарь…", width=84, command=self._open_dictionary, **btn_kw).pack(side="right", padx=(0, 6))

        self._acro_on = ctk.CTkSwitch(
            card, text="разбирать акронимы в главном окне",
            **self._switch_kw(self._apply_acronyms),
        )
        self._acro_on.pack(anchor="w", padx=inner_pad, pady=(4, 6))
        if cfg.get().acronyms_enabled:
            self._acro_on.select()

        self._pack_boxes: dict[str, ctk.CTkCheckBox] = {}
        listing = ctk.CTkFrame(
            card, fg_color=T.FIELD, corner_radius=T.CORNER_SM, border_width=1, border_color=T.LINE
        )
        listing.pack(fill="x", padx=inner_pad, pady=(0, inner_pad))

        found = acronyms.packs()
        if not found:
            ctk.CTkLabel(
                listing, text="словарей нет", text_color=T.INK_FAINT, font=ui_font(11)
            ).pack(anchor="w", padx=8, pady=6)
        for i, p in enumerate(found):
            where = "локально" if p.origin == "local" else "в репо"
            pady = (6, 3) if i == 0 else (0, 3 if i < len(found) - 1 else 6)
            if p.error:
                ctk.CTkLabel(
                    listing, text=f"{p.id} · не читается", text_color=T.ERR, font=ui_font(11)
                ).pack(anchor="w", padx=8, pady=pady)
                continue
            cb = ctk.CTkCheckBox(
                listing, text=f"{p.title} · {p.count} · {where}", width=20,
                checkbox_width=16, checkbox_height=16, corner_radius=3,
                border_width=1, fg_color=T.SWITCH_ON, hover_color=T.SWITCH_ON,
                border_color=T.LINE_STRONG, checkmark_color=T.SURFACE,
                text_color=T.INK, font=ui_font(11), command=self._apply_acronyms,
            )
            cb.pack(anchor="w", padx=8, pady=pady)
            if acronyms.is_enabled(p.id):
                cb.select()
            self._pack_boxes[p.id] = cb

    # ── tab: AI ───────────────────────────────────────────────────────────
    def _build_ai(self, card) -> None:
        from . import ai_token

        # The AI tab grew past any sensible window height (two prompt boxes +
        # the chivoblya toggle), and the bottom was clipped on the laptop. Put
        # the whole tab in a scrollable frame — the standard pattern for an
        # over-tall settings page — so nothing is ever cut off and the window
        # keeps a sane size.
        scroll = ctk.CTkScrollableFrame(
            card, fg_color="transparent", corner_radius=0,
            scrollbar_button_color=T.LINE, scrollbar_button_hover_color=T.LINE_STRONG,
        )
        scroll.pack(fill="both", expand=True)
        card = scroll

        inner_pad = T.INSET
        ctk.CTkLabel(
            card, text="ИИ-помощник", text_color=T.INK, font=ui_font(12, "bold")
        ).pack(anchor="w", padx=inner_pad, pady=(inner_pad, 0))

        self._ai_on = ctk.CTkSwitch(
            card, text="кнопки «причесать» и «объясни» в главном окне",
            **self._switch_kw(self._apply_ai),
        )
        self._ai_on.pack(anchor="w", padx=inner_pad, pady=(4, 6))
        if cfg.get().ai_enabled:
            self._ai_on.select()

        brow = ctk.CTkFrame(card, fg_color="transparent")
        brow.pack(fill="x", padx=inner_pad, pady=(0, 4))
        ctk.CTkLabel(brow, text="откуда отвечает ИИ", text_color=T.INK_FAINT, font=ui_font(11)).pack(anchor="w")
        self._ai_provider_labels = list(cfg.AI_PROVIDER_LABELS.values())
        self._ai_provider_inv = {v: k for k, v in cfg.AI_PROVIDER_LABELS.items()}
        self._ai_provider = ctk.CTkComboBox(
            brow, values=self._ai_provider_labels, width=230, height=T.CTRL_H,
            command=lambda _v: self._on_ai_provider(),
            fg_color=T.FIELD, border_color=T.LINE, button_color=T.LINE_STRONG,
            button_hover_color=T.INK_SOFT, text_color=T.INK,
            dropdown_fg_color=T.SURFACE, dropdown_text_color=T.INK, font=ui_font(12),
        )
        cur = cfg.get().ai_provider
        self._ai_provider.set(cfg.AI_PROVIDER_LABELS.get(cur, cfg.AI_PROVIDER_LABELS["gateway"]))
        self._ai_provider.pack(anchor="w", pady=(3, 0))
        tune_combobox(self._ai_provider)

        self._gemini_box = ctk.CTkFrame(card, fg_color="transparent")
        ctk.CTkLabel(
            self._gemini_box,
            text="ключ Google AI Studio (aistudio.google.com → Get API key)",
            text_color=T.INK_FAINT, font=ui_font(10), wraplength=460, justify="left",
        ).pack(anchor="w")
        krow = ctk.CTkFrame(self._gemini_box, fg_color="transparent")
        krow.pack(fill="x", pady=(3, 0))
        self._gemini_key = ctk.CTkEntry(
            krow, placeholder_text="вставь ключ сюда", show="•", height=T.CTRL_H,
            fg_color=T.FIELD, border_color=T.LINE, text_color=T.INK, font=ui_font(12),
        )
        self._gemini_key.pack(side="left", fill="x", expand=True)
        btn_kw = dict(
            height=T.CTRL_H, corner_radius=T.CORNER_SM, fg_color=T.SURFACE,
            border_width=1, border_color=T.LINE, hover_color=T.CHIP_HOVER,
            text_color=T.INK_SOFT, font=ui_font(11),
        )
        ctk.CTkButton(krow, text="сохранить", width=88, command=self._save_gemini_key, **btn_kw).pack(side="left", padx=(6, 0))
        ctk.CTkButton(krow, text="проверить", width=88, command=self._check_gemini_key, **btn_kw).pack(side="left", padx=(6, 0))
        ctk.CTkButton(krow, text="очистить", width=76, command=self._clear_gemini_key, **btn_kw).pack(side="left", padx=(6, 0))

        mrow = ctk.CTkFrame(card, fg_color="transparent")
        mrow.pack(fill="x", padx=inner_pad, pady=(4, 4))
        ctk.CTkLabel(mrow, text="модель", text_color=T.INK_FAINT, font=ui_font(11)).pack(anchor="w")
        self._ai_model = ctk.CTkComboBox(
            mrow, values=[], width=260, height=T.CTRL_H,
            command=lambda _v: self._apply_ai(),
            fg_color=T.FIELD, border_color=T.LINE, button_color=T.LINE_STRONG,
            button_hover_color=T.INK_SOFT, text_color=T.INK,
            dropdown_fg_color=T.SURFACE, dropdown_text_color=T.INK, font=ui_font(12),
        )
        self._ai_model.pack(anchor="w", pady=(3, 0))
        tune_combobox(self._ai_model)

        self._ai_state = ctk.CTkLabel(
            card, text="", text_color=T.INK_FAINT, font=ui_font(10),
            anchor="w", justify="left", wraplength=460,
        )
        self._ai_state.pack(anchor="w", padx=inner_pad, pady=(6, inner_pad))

        # two configurable AI functions (title + prompt each)
        fn_box = ctk.CTkFrame(card, fg_color="transparent")
        fn_box.pack(fill="x", padx=inner_pad, pady=(0, inner_pad))
        ctk.CTkLabel(
            fn_box, text="две кнопки-функции: подпись и свой промпт",
            text_color=T.INK_FAINT, font=ui_font(11),
        ).pack(anchor="w", pady=(0, 4))
        self._fn1_title, self._fn1_prompt = self._fn_fields(fn_box, 1)
        self._fn2_title, self._fn2_prompt = self._fn_fields(fn_box, 2)

        # chivoblya chip → runs function 2 on the selection
        self._chivo_fn2 = ctk.CTkSwitch(
            fn_box,
            text="чивобля при выделении сразу запускает кнопку 2",
            **self._switch_kw(self._apply_ai),
        )
        self._chivo_fn2.pack(anchor="w", pady=(2, 0))
        if cfg.get().ai_chivoblya_fn2:
            self._chivo_fn2.select()
        ctk.CTkLabel(
            fn_box,
            text="нажал «чивобля?» на выделенном тексте — откроется окно и "
                 "сработает кнопка 2 с её промптом (расширенный перевод). "
                 "выключи, если чивобля должна просто открывать окно.",
            text_color=T.INK_FAINT, font=ui_font(10), wraplength=460, justify="left",
        ).pack(anchor="w", pady=(2, 0))

        self._refresh_ai_models()
        self._sync_ai_state()
        ai_token.on_change(self._on_ai_token)

    def _fn_fields(self, parent, n: int):
        """One labelled title-entry + prompt-textbox pair. Returns (title, prompt)."""
        from . import assistant

        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.pack(fill="x", pady=(0, 8))
        default_title = assistant.DEFAULT_FN1_TITLE if n == 1 else assistant.DEFAULT_FN2_TITLE
        default_prompt = assistant.POLISH_PROMPT if n == 1 else assistant.EXPLAIN_PROMPT
        title_val = getattr(cfg.get(), f"ai_fn{n}_title", "") or default_title
        prompt_val = getattr(cfg.get(), f"ai_fn{n}_prompt", "")

        row = ctk.CTkFrame(box, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkLabel(
            row, text=f"кнопка {n}", text_color=T.INK, font=ui_font(11, "bold"), width=64, anchor="w"
        ).pack(side="left")
        title = ctk.CTkEntry(
            row, height=T.CTRL_H, fg_color=T.FIELD, border_color=T.LINE,
            text_color=T.INK, font=ui_font(12), placeholder_text=default_title,
        )
        title.pack(side="left", fill="x", expand=True, padx=(6, 0))
        title.insert(0, title_val)

        prompt = ctk.CTkTextbox(
            box, height=80, fg_color=T.FIELD, border_color=T.LINE, border_width=1,
            text_color=T.INK, font=ui_font(11), wrap="word", corner_radius=T.CORNER_SM,
        )
        prompt.pack(fill="x", pady=(3, 0))
        prompt.insert("1.0", prompt_val if prompt_val.strip() else default_prompt)
        # word-wrap never needs the horizontal bar CTkTextbox auto-packs, and that
        # 10px misaligns the two prompt boxes. CTk schedules its own
        # _check_if_scrollbars_needed 50ms after __init__ (and re-runs it on every
        # insert), so hiding immediately gets undone — hide AFTER that timer fires.
        def _no_h_scroll(pb=prompt) -> None:
            try:
                pb._hide_x_scrollbar = True
                pb._create_grid_for_text_and_scrollbars(re_grid_x_scrollbar=True)
            except Exception:  # noqa: BLE001
                pass

        try:
            prompt.after(80, _no_h_scroll)
        except Exception:  # noqa: BLE001
            _no_h_scroll()

        def save(_e=None) -> None:
            t = title.get().strip() or default_title
            praw = prompt.get("1.0", "end-1c").strip()
            cfg.update(**{
                f"ai_fn{n}_title": t,
                # blank or untouched-default stores as "" → built-in stays the source of truth
                f"ai_fn{n}_prompt": "" if (not praw or praw == default_prompt.strip()) else praw,
            })
            self._status.configure(text=f"ИИ · кнопка {n} сохранена")

        title.bind("<FocusOut>", save)
        prompt.bind("<FocusOut>", save)
        return title, prompt

    def _current_ai_provider(self) -> str:
        return self._ai_provider_inv.get(self._ai_provider.get(), "gateway")

    def _on_ai_provider(self) -> None:
        cfg.update(ai_provider=self._current_ai_provider())
        self._refresh_ai_models()
        self._sync_ai_state()
        self._status.configure(text="ИИ · применено")

    def _refresh_ai_models(self) -> None:
        from . import ai_config

        prov = self._current_ai_provider()
        if prov == "gemini":
            self._ai_default = f"по умолчанию ({ai_config.gemini_model()})"
            values = [self._ai_default, *ai_config.gemini_models()]
            saved = cfg.get().ai_gemini_model
        else:
            self._ai_default = f"как в ai.json ({ai_config.model() or '—'})"
            values = [self._ai_default, *ai_config.models()]
            saved = cfg.get().ai_model
        try:
            self._ai_model.configure(values=values)
            self._ai_model.set(saved or self._ai_default)
        except Exception:  # noqa: BLE001
            pass
        try:
            if prov == "gemini":
                self._gemini_box.pack(
                    fill="x", padx=T.INSET, pady=(0, 4), after=self._ai_provider.master
                )
            else:
                self._gemini_box.pack_forget()
        except Exception:  # noqa: BLE001
            pass

    def _save_gemini_key(self) -> None:
        from . import ai_secrets

        ok, msg = ai_secrets.set_key("gemini", self._gemini_key.get())
        if ok:
            self._gemini_key.delete(0, "end")
        self._status.configure(text=msg)
        self._sync_ai_state()

    def _clear_gemini_key(self) -> None:
        from . import ai_secrets

        ai_secrets.clear_key("gemini")
        self._gemini_key.delete(0, "end")
        self._status.configure(text="ключ Gemini удалён")
        self._sync_ai_state()

    def _check_gemini_key(self) -> None:
        import threading

        from . import ai_client, ai_secrets

        key = self._gemini_key.get().strip() or ai_secrets.get_key("gemini")
        if not key:
            self._status.configure(text="сначала вставь или сохрани ключ")
            return
        self._status.configure(text="проверяю ключ…")

        def work() -> None:
            ok, msg = ai_client.check_gemini_key(key)
            try:
                self.after(0, lambda: self._status.configure(text=msg))
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=work, daemon=True).start()

    def _sync_ai_state(self) -> None:
        from . import ai_config, ai_secrets, ai_token

        prov = self._current_ai_provider()
        if prov == "gemini":
            if not ai_secrets.available():
                text = "для шифрования ключа нужен пакет cryptography:\npip install cryptography"
            elif ai_secrets.has_key("gemini"):
                text = f"ключ Gemini сохранён ({ai_secrets.key_hint('gemini')}) · зашифрован на этом ПК"
            else:
                text = "ключа нет — вставь свой ключ Google AI Studio выше и нажми «сохранить»"
        else:
            if not ai_config.configured():
                text = f"нет настроек шлюза — положи ai.json сюда:\n{ai_config.where()}"
            elif not ai_token.present():
                text = "токен не вставлен — нажми 🔑 в главном окне (сначала скопируй токен в буфер)"
            else:
                left = ai_token.seconds_left()
                who = ai_token.user() or "токен"
                text = f"{who} · {left // 60}м осталось" if left else f"{who} · истёк"
        try:
            self._ai_state.configure(text=text)
        except Exception:  # noqa: BLE001
            pass

    def _on_ai_token(self) -> None:
        try:
            self.after(0, self._sync_ai_state)
        except Exception:  # noqa: BLE001
            pass

    def _apply_ai(self) -> None:
        picked = self._ai_model.get()
        chivo_fn2 = (
            bool(self._chivo_fn2.get()) if hasattr(self, "_chivo_fn2") else cfg.get().ai_chivoblya_fn2
        )
        if self._current_ai_provider() == "gemini":
            cfg.update(
                ai_enabled=bool(self._ai_on.get()),
                ai_gemini_model="" if picked == self._ai_default else picked,
                ai_chivoblya_fn2=chivo_fn2,
            )
        else:
            cfg.update(
                ai_enabled=bool(self._ai_on.get()),
                ai_model="" if picked == self._ai_default else picked,
                ai_chivoblya_fn2=chivo_fn2,
            )
        self._status.configure(text="ИИ · применено")

    def _apply_acronyms(self) -> None:
        cfg.update(
            acronyms_enabled=bool(self._acro_on.get()),
            acronym_packs={pid: bool(cb.get()) for pid, cb in self._pack_boxes.items()},
        )
        self._status.configure(text="словари · применено")

    # ── theme / hotkey / switches ─────────────────────────────────────────
    def _theme_btn(self, parent, key, label, *, side, padx=(0, 0)):
        btn = ctk.CTkButton(
            parent, text=label, width=88, height=T.ROW_H,
            corner_radius=T.ROW_H // 2, fg_color=T.SURFACE, border_width=1,
            border_color=T.LINE, hover_color=T.CHIP_HOVER, text_color=T.INK,
            font=ui_font(11), command=lambda k=key: self._on_theme(k),
        )
        btn.pack(side=side, padx=padx)
        return btn

    def _sync_theme_buttons(self) -> None:
        for key, btn in self._theme_btns.items():
            on = key == self._ui_theme
            btn.configure(
                fg_color=T.ACCENT if on else T.SURFACE,
                hover_color=T.ACCENT_HOVER if on else T.CHIP_HOVER,
                text_color=T.ON_ACCENT if on else T.INK,
                border_color=T.ACCENT if on else T.LINE,
            )

    def _on_theme(self, key: str) -> None:
        if key not in T.THEME_CHOICES:
            return
        self._ui_theme = key
        self._sync_theme_buttons()
        cfg.update(ui_theme=key)
        self._status.configure(text="тема · применено")
        master = self.master
        self._close()
        if master is not None:
            try:
                master.after(30, master.open_settings)
            except Exception:  # noqa: BLE001
                pass

    def _mode_btn(self, parent, label, *, side, padx=(0, 0)):
        mode = "double" if label == _MODE_DOUBLE else "combo"

        def pick() -> None:
            self._on_mode(mode)

        btn = ctk.CTkButton(
            parent, text=label, width=148 if mode == "double" else 120,
            height=T.ROW_H, corner_radius=T.ROW_H // 2, fg_color=T.SURFACE,
            border_width=1, border_color=T.LINE, hover_color=T.CHIP_HOVER,
            text_color=T.INK, font=ui_font(11), command=pick,
        )
        btn.pack(side=side, padx=padx)
        return btn

    def _sync_mode_buttons(self) -> None:
        active = _MODE_DOUBLE if self._hk.mode == "double" else _MODE_COMBO
        for label, btn in self._mode_btns.items():
            on = label == active
            btn.configure(
                fg_color=T.ACCENT if on else T.SURFACE,
                hover_color=T.ACCENT_HOVER if on else T.CHIP_HOVER,
                text_color=T.ON_ACCENT if on else T.INK,
                border_color=T.ACCENT if on else T.LINE,
            )

    def _on_mode(self, mode: str) -> None:
        self._hk = HotkeySpec(
            scan_code=self._hk.scan_code, ctrl=self._hk.ctrl,
            shift=self._hk.shift, alt=self._hk.alt, win=self._hk.win, mode=mode,
        )
        self._sync_mode_buttons()
        self._hk_label.configure(text=self._hk.label())
        self._try_save_hotkey()

    def _reset_hotkey(self) -> None:
        self._stop_capture()
        self._hk = HotkeySpec()
        self._sync_mode_buttons()
        self._hk_label.configure(text=self._hk.label())
        self._hk_hint.configure(text="сброшено на Ctrl+Alt+E (как Crow)", text_color=T.INK_FAINT)
        self._try_save_hotkey()

    def _start_capture(self) -> None:
        if keyboard is None:
            self._hk_hint.configure(text="пакет keyboard не установлен", text_color=T.ERR)
            return
        self._stop_capture()
        self._btn_rec.configure(text="…жмите клавиши", state="disabled")
        self._hk_hint.configure(
            text="слушаю: Ctrl / Shift / Alt / Win + клавиша (или одна клавиша для ×2)",
            text_color=T.INK,
        )

        def on_event(event: object) -> None:
            if getattr(event, "event_type", None) != "down":
                return
            name = str(getattr(event, "name", "") or "").lower()
            if name in (
                "ctrl", "left ctrl", "right ctrl", "shift", "left shift",
                "right shift", "alt", "left alt", "right alt", "windows",
                "left windows", "right windows", "cmd",
            ):
                try:
                    parts = []
                    if keyboard.is_pressed("ctrl"):
                        parts.append("Ctrl")
                    if keyboard.is_pressed("shift"):
                        parts.append("Shift")
                    if keyboard.is_pressed("alt"):
                        parts.append("Alt")
                    if keyboard.is_pressed("windows") or keyboard.is_pressed("cmd"):
                        parts.append("Win")
                    self.after(
                        0,
                        lambda p="+".join(parts) or "…": self._hk_hint.configure(
                            text=f"модификаторы: {p}  +  (жмите основную клавишу)",
                            text_color=T.INK,
                        ),
                    )
                except Exception:  # noqa: BLE001
                    pass
                return

            try:
                sc = int(getattr(event, "scan_code", -1))
            except Exception:  # noqa: BLE001
                return
            if sc < 0:
                return
            try:
                ctrl = bool(keyboard.is_pressed("ctrl"))
                shift = bool(keyboard.is_pressed("shift"))
                alt = bool(keyboard.is_pressed("alt"))
                win = bool(keyboard.is_pressed("windows") or keyboard.is_pressed("cmd"))
            except Exception:  # noqa: BLE001
                ctrl = shift = alt = win = False

            mode = "combo" if (ctrl or shift or alt or win) else "double"
            ui_mode = "double" if self._hk.mode == "double" else "combo"
            if ui_mode == "combo" and not (ctrl or shift or alt or win):
                mode = "combo"
            elif ui_mode == "double":
                mode = "double"

            spec = HotkeySpec(scan_code=sc, ctrl=ctrl, shift=shift, alt=alt, win=win, mode=mode)
            self.after(0, lambda: self._finish_capture(spec))

        self._capture_hook = keyboard.hook(on_event, suppress=False)

    def _finish_capture(self, spec: HotkeySpec) -> None:
        self._stop_capture()
        self._btn_rec.configure(text="записать…", state="normal")
        self._hk = spec
        self._sync_mode_buttons()
        self._hk_label.configure(text=spec.label())
        reason = check_reserved(spec)
        if reason:
            self._hk_hint.configure(text=f"⚠ {reason}", text_color=T.ERR)
            self._status.configure(text="не сохранено — конфликт")
            return
        self._hk_hint.configure(text=f"записано: {spec.label()}", text_color=T.OK)
        self._try_save_hotkey()

    def _try_save_hotkey(self) -> None:
        reason = check_reserved(self._hk)
        if reason:
            self._hk_hint.configure(text=f"⚠ {reason}", text_color=T.ERR)
            self._status.configure(text="конфликт с Windows")
            return
        cfg.update(hotkey=self._hk.to_dict())
        self._status.configure(text="сохранено · применено")

    def _apply_switches(self) -> None:
        pid = self._pmap.get(self._prov.get(), tr.DEFAULT_PROVIDER_ID)
        want_autostart = bool(self._autostart.get())
        cfg.update(
            instant_translate=bool(self._instant.get()),
            chivoblya_enabled=bool(self._chivo.get()),
            autostart=want_autostart,
            close_to_tray=bool(self._close_tray.get()),
            sync_scroll=bool(self._sync_scroll.get()),
            spotlight=bool(self._spotlight.get()),
            show_examples=False,
            provider_id=pid,
            ui_theme=self._ui_theme,
        )
        ok, err = sync_autostart(want_autostart)
        if not ok:
            self._status.configure(text=(err or "автозапуск не применился")[:48])
            return
        self._status.configure(text="сохранено")

    def _open_dictionary(self) -> None:
        open_win = getattr(self.master, "open_acro_window", None)
        if open_win is None:
            self._status.configure(text="словарь недоступен")
            return
        self._close()
        try:
            open_win("")
        except Exception:  # noqa: BLE001
            pass

    def _open_packs_dir(self) -> None:
        import os

        from . import acronyms

        try:
            os.startfile(str(acronyms.local_dir()))  # noqa: S606
        except Exception:  # noqa: BLE001
            self._status.configure(text="не удалось открыть папку")

    def _stop_capture(self) -> None:
        if self._capture_hook is not None and keyboard is not None:
            try:
                keyboard.unhook(self._capture_hook)
            except Exception:  # noqa: BLE001
                pass
        self._capture_hook = None
        try:
            self._btn_rec.configure(text="записать…", state="normal")
        except Exception:  # noqa: BLE001
            pass

    def _close(self) -> None:
        from . import ai_token

        self._stop_capture()
        ai_token.off_change(self._on_ai_token)
        self.destroy()