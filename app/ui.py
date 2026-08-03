"""Main dual-pane — native Windows caption, Segoe UI / UTF-8."""

from __future__ import annotations

import threading
from collections.abc import Callable

import customtkinter as ctk
import pyperclip

from . import languages as langs
from . import logutil
from . import settings as cfg
from . import theme as T
from . import translators as tr
from .restart import schedule_relaunch
from .settings_ui import SettingsWindow
from .theme import apply_appearance, apply_theme, mdl2_font, ui_font
from .app_icon import apply as apply_app_icon
from .ui_widgets import tune_combobox
from .translators.base import TranslateResult

apply_appearance()

APP_VERSION = T.APP_VERSION


class TranslatorApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        s = cfg.load()
        apply_theme(s.ui_theme)
        # native Windows caption, empty title text
        self.title("")
        self.geometry("1000x560")
        self.minsize(760, 440)
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

        self._shell = ctk.CTkFrame(
            self, fg_color=T.BG, border_width=0, corner_radius=0
        )
        self._shell.pack(fill="both", expand=True)

        self._build(self._shell)
        cfg.on_change(self._on_settings_changed)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Unmap>", self._on_unmap)

        self.after(80, lambda: apply_app_icon(self))

        label = next(
            (lb for pid, lb, _ in tr.list_providers() if pid == self._provider.get()),
            None,
        )
        if label:
            self._provider_combo.set(label)

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
        Full-width toolbar (pack) + 3-col pane grid:
          [ brand ………… ⇄ ………… Google · перевести · … ]   ← whole content width
          [ source pane ] | MID_W | [ target pane ]         ← mirror panes
        Tools must not live only in the right pane column (overflow → paint-over).
        """
        content = ctk.CTkFrame(parent, fg_color=T.BG)
        content.pack(fill="both", expand=True, padx=T.PAD, pady=(T.GAP, 0))

        # ── toolbar one line: brand | ⇄ (true center over panes) | tools ──
        toolbar = ctk.CTkFrame(content, fg_color="transparent", height=T.HEAD_H)
        toolbar.pack(fill="x", pady=(0, T.GAP))
        toolbar.pack_propagate(False)

        vpad = (T.HEAD_H - T.ROW_H) // 2

        mark = ctk.CTkFrame(toolbar, fg_color="transparent", height=T.HEAD_H)
        mark.pack(side="left", fill="y")
        mark.grid_rowconfigure(0, weight=1)
        ctk.CTkLabel(
            mark,
            text="Bonjour",
            font=ui_font(T.FONT_BRAND_SIZE),
            text_color=T.INK,
        ).grid(row=0, column=0, sticky="s")
        ctk.CTkLabel(
            mark,
            text=f" {T.BRAND_CYR}",
            font=ui_font(T.FONT_BRAND_CYR_SIZE, "bold"),
            text_color=T.INK,
        ).grid(row=0, column=1, sticky="s")
        ctk.CTkLabel(
            mark,
            text=f" {APP_VERSION}",
            font=ui_font(T.FONT_VERSION_SIZE),
            text_color=T.INK_SOFT,
        ).grid(row=0, column=2, sticky="s", pady=(0, 8))
        # circular arrow — hard kill + relaunch (dev reload without TC)
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
            command=self._restart_client,
        ).grid(row=0, column=3, sticky="s", padx=(6, 0), pady=(0, 1))

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
        self._btn_swap.place(relx=0.5, rely=0.5, anchor="center")

        tools = ctk.CTkFrame(toolbar, fg_color="transparent", height=T.ROW_H)
        tools.pack(side="right", pady=vpad)

        prov_wrap = ctk.CTkFrame(tools, fg_color="transparent", height=T.ROW_H)
        prov_wrap.pack(side="left", padx=(0, T.TOOL_GAP))
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
        self._provider_dot.pack(side="left", padx=(T.GAP, 0))

        self._btn_translate = ctk.CTkButton(
            tools,
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
        self._btn_translate.pack(side="left", padx=(T.TOOL_GAP, 0))

        self._ghost(tools, "очистить", self.clear_all, w=80).pack(
            side="left", padx=(T.TOOL_GAP, 0)
        )
        self._settings_btn(tools).pack(side="left", padx=(T.TOOL_GAP, 0))

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

        # footer: tagline слева · hotkey справа (без центрального статуса)
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

        ctk.CTkLabel(
            bar,
            text=role,
            font=ui_font(11),
            text_color=T.INK_FAINT,
            anchor="center",
        ).grid(row=0, column=1, sticky="ew")

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
            self._src_box.bind("<<Paste>>", self._on_src_paste)
            self._src_box.bind("<Control-v>", self._on_src_paste)
            self._src_box.bind("<Control-V>", self._on_src_paste)
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

        if side == "target":
            self._tgt_pane = frame
        else:
            self._src_pane = frame

        return frame

    def _textbox(self, parent) -> ctk.CTkTextbox:
        return ctk.CTkTextbox(
            parent,
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

        try:
            self.after(0, apply)
        except Exception:  # noqa: BLE001
            apply()

    def _restyle_theme(self, preference: str) -> None:
        """Rebuild chrome so palette tokens stick after light/dark/auto switch."""
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

    def set_source_text(self, text: str) -> None:
        from . import logutil
        from .selection import sanitize_selection

        text = sanitize_selection(text)
        log = logutil.get()
        log.debug("set_source_text len=%s head=%r", len(text), text[:100])
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
            (got or "")[:80],
        )

    def get_source_text(self) -> str:
        inner = self._inner(self._src_box)
        try:
            return inner.get("1.0", "end-1c")
        except Exception:  # noqa: BLE001
            return self._src_box.get("1.0", "end-1c")

    def set_target_text(self, text: str) -> None:
        text = text or ""
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

    def _show_translate_progress(self) -> None:
        """Clear stale translation and show calm loading state."""
        self._cancel_progress_anim()
        self._tgt_progress = True
        try:
            self._tgt_box.configure(text_color=T.INK_FAINT)
            self._tgt_pane.configure(border_color=T.INK_SOFT, border_width=2)
        except Exception:  # noqa: BLE001
            pass
        self.set_target_text("переводим")
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
        self.set_target_text(f"переводим{dots}")
        try:
            self._progress_after_id = self.after(420, self._progress_anim)
        except Exception:  # noqa: BLE001
            pass

    def copy_source(self) -> None:
        t = self.get_source_text()
        if t:
            try:
                pyperclip.copy(t)
            except Exception as exc:  # noqa: BLE001
                logutil.get().warning("copy source: %s", exc)

    def copy_target(self) -> None:
        t = self._inner(self._tgt_box).get("1.0", "end-1c")
        if t:
            try:
                pyperclip.copy(t)
            except Exception as exc:  # noqa: BLE001
                logutil.get().warning("copy target: %s", exc)

    def clear_source(self) -> None:
        self.set_source_text("")

    def clear_target(self) -> None:
        self.set_target_text("")

    def clear_all(self) -> None:
        self._translate_job += 1
        self._cancel_progress_anim()
        self._busy = False
        self._btn_translate.configure(state="normal")
        try:
            self._tgt_box.configure(text_color=T.INK)
        except Exception:  # noqa: BLE001
            pass
        self.clear_source()
        self.clear_target()
        self._end_translate_progress_ui()

    def _on_src_paste(self, _e=None) -> None:
        self.after(50, self._maybe_instant)

    def _maybe_instant(self) -> None:
        if cfg.get().instant_translate and self.get_source_text().strip():
            self.translate_now()

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

    def translate_now(self) -> None:
        text = self.get_source_text().strip()
        if not text:
            return
        self._translate_job += 1
        job = self._translate_job
        self._busy = True
        self._btn_translate.configure(state="disabled")
        self._show_translate_progress()
        source, target, provider_id = (
            self._source_lang.get(),
            self._target_lang.get(),
            self._provider.get(),
        )

        def work() -> None:
            result = tr.translate(text, source=source, target=target, provider_id=provider_id)
            self.after(0, lambda: self._apply_result(result, job))

        threading.Thread(target=work, daemon=True).start()

    def _apply_result(self, result: TranslateResult, job: int) -> None:
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
        self.set_target_text(result.text)

    def bring_with_selection(self, text: str) -> None:
        """Fill source on UI thread. Chip click is already on main thread → run now."""
        import threading

        from . import logutil
        from .selection import sanitize_selection

        text = sanitize_selection(text)
        log = logutil.get()
        log.info(
            "bring_with_selection called len=%s head=%r thread=%s",
            len(text),
            text[:100],
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
            except Exception:  # noqa: BLE001
                pass
            ok = bool(got)
            log.info("bring done ok=%s len=%s head=%r", ok, len(got), got[:80])
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

    def _restart_client(self) -> None:
        """Full process kill + fresh start (after name/version ↻)."""
        import os

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
        # Stop tray / destroy best-effort, then hard-exit so mutex drops.
        # after() is useless here — destroy ends mainloop; os._exit is immediate.
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
