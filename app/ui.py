"""Main dual-pane — custom chrome (no Windows title bar), Segoe UI / UTF-8."""

from __future__ import annotations

import threading
from collections.abc import Callable

import customtkinter as ctk
import pyperclip

from . import languages as langs
from . import settings as cfg
from . import theme as T
from . import translators as tr
from . import winframe
from .settings_ui import SettingsWindow
from .theme import apply_appearance, ui_font
from .translators.base import TranslateResult

apply_appearance()

APP_VERSION = T.APP_VERSION


class TranslatorApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        s = cfg.load()
        # short taskbar name only — no version, no second "epta" block in OS chrome
        self.title(T.APP_NAME)
        self.geometry("1000x580")
        self.minsize(760, 460)
        self.configure(fg_color=T.BG)

        # remove Windows caption/min/max/close — we draw our own
        self.overrideredirect(True)
        self._maximized = False
        self._restore_geom = "1000x580+120+80"
        self._drag = {"x": 0, "y": 0}

        self._source_lang = ctk.StringVar(value=s.source_lang or "auto")
        self._target_lang = ctk.StringVar(value=s.target_lang or "ru")
        self._provider = ctk.StringVar(value=s.provider_id or tr.DEFAULT_PROVIDER_ID)
        self._status = ctk.StringVar(value="готов")
        self._busy = False
        self._settings_win: SettingsWindow | None = None
        self._translate_job = 0

        # thin outer border (frameless needs an edge)
        self._shell = ctk.CTkFrame(
            self, fg_color=T.BG, border_width=1, border_color=T.LINE, corner_radius=0
        )
        self._shell.pack(fill="both", expand=True)

        self._build_titlebar(self._shell)
        self._build(self._shell)
        cfg.on_change(self._on_settings_changed)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # taskbar icon after map
        self.after(80, lambda: winframe.make_appwindow(self))

        label = next(
            (lb for pid, lb, _ in tr.list_providers() if pid == self._provider.get()),
            None,
        )
        if label:
            self._provider_combo.set(label)

    # ── custom title bar: only drag + window buttons (no brand text) ──
    def _build_titlebar(self, parent: ctk.CTkFrame) -> None:
        bar = ctk.CTkFrame(parent, fg_color=T.TITLE_BG, height=T.TITLE_H, corner_radius=0)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        # empty drag zone (brand lives in content, large, as before)
        drag = ctk.CTkFrame(bar, fg_color="transparent")
        drag.pack(side="left", fill="both", expand=True)

        controls = ctk.CTkFrame(bar, fg_color="transparent")
        controls.pack(side="right", padx=(0, 4))

        def win_btn(text: str, cmd) -> ctk.CTkButton:
            return ctk.CTkButton(
                controls,
                text=text,
                width=46,
                height=T.TITLE_H - 2,
                corner_radius=0,
                fg_color="transparent",
                hover_color=T.TITLE_BTN_HOVER,
                text_color=T.INK,
                font=ui_font(12),
                command=cmd,
            )

        win_btn("—", self._minimize).pack(side="left")
        self._btn_max = win_btn("□", self._toggle_max)
        self._btn_max.pack(side="left")
        ctk.CTkButton(
            controls,
            text="✕",
            width=46,
            height=T.TITLE_H - 2,
            corner_radius=0,
            fg_color="transparent",
            hover_color=T.TITLE_CLOSE_HOVER,
            text_color=T.INK,
            font=ui_font(12),
            command=self._on_close,
        ).pack(side="left")

        for w in (bar, drag):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<Double-Button-1>", lambda _e: self._toggle_max())

    def _drag_start(self, event) -> None:
        if self._maximized:
            return
        self._drag["x"] = event.x_root - self.winfo_x()
        self._drag["y"] = event.y_root - self.winfo_y()

    def _drag_move(self, event) -> None:
        if self._maximized:
            return
        x = event.x_root - self._drag["x"]
        y = event.y_root - self._drag["y"]
        self.geometry(f"+{x}+{y}")

    def _minimize(self) -> None:
        # overrideredirect: iconify is flaky — use Win32 show minimized
        try:
            import ctypes

            hwnd = winframe.hwnd_of(self)
            # SW_MINIMIZE = 6
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 6)
                return
        except Exception:  # noqa: BLE001
            pass
        try:
            self.iconify()
        except Exception:  # noqa: BLE001
            pass

    def _toggle_max(self) -> None:
        if self._maximized:
            self.geometry(self._restore_geom)
            self._maximized = False
            self._btn_max.configure(text="□")
        else:
            self._restore_geom = self.geometry()
            x, y, w, h = winframe.work_area()
            self.geometry(f"{w}x{h}+{x}+{y}")
            self._maximized = True
            self._btn_max.configure(text="❐")

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

        # tools right first so brand stays left; ⇄ placed on full toolbar center
        tools = ctk.CTkFrame(toolbar, fg_color="transparent")
        tools.pack(side="right")

        mark = ctk.CTkFrame(toolbar, fg_color="transparent")
        mark.pack(side="left")
        ctk.CTkLabel(
            mark,
            text="bonjour",
            font=ctk.CTkFont(family="Georgia", size=26, weight="normal"),
            text_color=T.INK,
        ).pack(side="left")
        ctk.CTkLabel(
            mark,
            text=f" {T.BRAND_CYR}",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color=T.INK,
        ).pack(side="left")

        # geometric center of toolbar = center between the two equal panes below
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

        prov_wrap = ctk.CTkFrame(tools, fg_color="transparent")
        prov_wrap.pack(side="left", padx=(0, 8))

        self._provider_map = {label: pid for pid, label, _ in tr.list_providers()}
        provider_labels = [label for _, label, _ in tr.list_providers()]
        default_label = next(
            label for pid, label, _ in tr.list_providers() if pid == self._provider.get()
        )
        self._provider_combo = ctk.CTkComboBox(
            prov_wrap,
            values=provider_labels,
            width=110,
            height=T.ROW_H,
            command=self._on_provider_ui,
            fg_color=T.SURFACE,
            border_color=T.LINE,
            button_color=T.LINE_STRONG,
            button_hover_color=T.INK_SOFT,
            text_color=T.INK,
            dropdown_fg_color=T.SURFACE,
            dropdown_text_color=T.INK,
            font=ui_font(12),
        )
        self._provider_combo.set(default_label)
        self._provider_combo.pack(side="left")

        # provider ● — larger, closer to control icon weight
        self._provider_dot = ctk.CTkLabel(
            prov_wrap,
            text="●",
            width=T.DOT_SIZE + 4,
            height=T.ROW_H,
            font=ui_font(T.DOT_SIZE),
            text_color=T.INK_FAINT,
        )
        self._provider_dot.pack(side="left", padx=(6, 0))

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
        self._btn_translate.pack(side="left", padx=(0, 6))

        self._ghost(tools, "очистить", self.clear_all, w=80).pack(side="left", padx=(0, 6))
        self._ghost(tools, "стиль", self.open_style_picker, w=64).pack(
            side="left", padx=(0, 6)
        )
        self._ghost(tools, "⚙", self.open_settings, w=36).pack(side="left")

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

        # footer: tagline left · version·hotkey right (status not on chrome)
        foot = ctk.CTkFrame(parent, fg_color=T.BG, height=T.FOOT_H)
        foot.pack(fill="x", padx=T.PAD, pady=(T.GAP, T.PAD))
        foot.pack_propagate(False)

        ctk.CTkLabel(
            foot,
            text=T.TAGLINE,
            text_color=T.INK_FAINT,
            font=ui_font(11),
            anchor="w",
        ).pack(side="left")
        self._hk_foot = ctk.CTkLabel(
            foot,
            text=self._hotkey_footer(),
            text_color=T.INK_FAINT,
            font=ui_font(11),
            anchor="e",
        )
        self._hk_foot.pack(side="right")

        # status kept for logic/color updates — not packed (was "готов CtrlAltE…")
        self._status_lbl = ctk.CTkLabel(
            foot,
            textvariable=self._status,
            text_color=T.INK_FAINT,
            font=ui_font(11),
        )

        self.bind("<Control-Return>", lambda _e: self.translate_now())
        self.bind("<Control-l>", lambda _e: self.clear_all())
        self.after(200, self._probe_provider)

    def _hotkey_footer(self) -> str:
        try:
            return f"v{APP_VERSION}  ·  {cfg.get().hotkey_spec().label()}"
        except Exception:  # noqa: BLE001
            return f"v{APP_VERSION}"

    def _make_pane(self, parent: ctk.CTkFrame, side: str) -> ctk.CTkFrame:
        """Identical card for source and target — same INSET, bar, field."""
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
        bar.grid_propagate(False)

        combo_kw = dict(
            width=168,
            height=T.CTRL_H,
            fg_color=T.FIELD,
            border_color=T.LINE,
            button_color=T.LINE_STRONG,
            text_color=T.INK,
            dropdown_fg_color=T.SURFACE,
            font=ui_font(12),
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
            self._src_combo.pack(side="left", pady=0)
            # pack right-edge first so visual order is [✕] [копир.]
            self._icon(bar, "копир.", self.copy_source, T.COPY_W).pack(
                side="right", pady=0
            )
            self._icon(bar, "✕", self.clear_source, T.ICON_W).pack(
                side="right", padx=(0, 6), pady=0
            )

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
            self._tgt_combo.pack(side="left", pady=0)
            self._icon(bar, "копир.", self.copy_target, T.COPY_W).pack(
                side="right", pady=0
            )
            self._icon(bar, "✕", self.clear_target, T.ICON_W).pack(
                side="right", padx=(0, 6), pady=0
            )

            self._tgt_box = self._textbox(frame)
            self._tgt_box.grid(
                row=1, column=0, sticky="nsew", padx=T.INSET, pady=(0, T.INSET)
            )

        return frame

    def _textbox(self, parent) -> ctk.CTkTextbox:
        return ctk.CTkTextbox(
            parent,
            fg_color=T.FIELD,
            text_color=T.INK,
            border_width=1,
            border_color=T.LINE,
            border_spacing=T.TEXT_BORDER_SPACING,
            font=ui_font(15),
            wrap="word",
            corner_radius=T.CORNER_SM,
            scrollbar_button_color=T.LINE,
            scrollbar_button_hover_color=T.LINE_STRONG,
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
            self._status.set(f"стиль чипа #{sid}")
            # notify main if it registered a chip refresh hook
            cb = getattr(self, "on_chip_style_changed", None)
            if cb:
                try:
                    cb(sid)
                except Exception:  # noqa: BLE001
                    pass

        self._style_win = StylePickerWindow(self, on_saved=saved)

    def _on_settings_changed(self, s: cfg.AppSettings) -> None:
        def apply() -> None:
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
            self._status.set("настройки")

        try:
            self.after(0, apply)
        except Exception:  # noqa: BLE001
            apply()

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

        text = text or ""
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

    def copy_source(self) -> None:
        t = self.get_source_text()
        if t:
            try:
                pyperclip.copy(t)
                self._status.set("скопировано ←")
            except Exception as exc:  # noqa: BLE001
                self._status.set(str(exc)[:40])

    def copy_target(self) -> None:
        t = self._inner(self._tgt_box).get("1.0", "end-1c")
        if t:
            try:
                pyperclip.copy(t)
                self._status.set("скопировано →")
            except Exception as exc:  # noqa: BLE001
                self._status.set(str(exc)[:40])

    def clear_source(self) -> None:
        self.set_source_text("")

    def clear_target(self) -> None:
        self.set_target_text("")

    def clear_all(self) -> None:
        self.clear_source()
        self.clear_target()
        self._status.set("очищено")

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
        if self._busy:
            return
        text = self.get_source_text().strip()
        if not text:
            self._status.set("нет текста")
            return
        self._busy = True
        self._status.set("…")
        self._btn_translate.configure(state="disabled")
        self._translate_job += 1
        job = self._translate_job
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
        self._busy = False
        self._btn_translate.configure(state="normal")
        if not result.ok:
            self._status.set(f"ошибка: {(result.error or '')[:48]}")
            self._status_lbl.configure(text_color=T.ERR)
            self.set_target_text("")
            return
        self._status_lbl.configure(text_color=T.INK_FAINT)
        self.set_target_text(result.text)
        bits = [result.provider or "ok"]
        if result.detected_source and self._source_lang.get() == "auto":
            bits.append(result.detected_source)
        self._status.set(" · ".join(bits))

    def bring_with_selection(self, text: str) -> None:
        """Fill source on UI thread. Chip click is already on main thread → run now."""
        import threading

        from . import logutil

        text = (text or "").strip()
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
                self._status.set("нет текста")
                log.warning("bring ui: empty text")
                return
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
            self._status.set(f"вставлено · {len(got)} зн." if ok else "вставка не удалась")
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

    def _on_close(self) -> None:
        self.destroy()


def run_app() -> TranslatorApp:
    return TranslatorApp()
