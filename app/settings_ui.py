"""Settings — live apply; interactive hotkey capture."""

from __future__ import annotations

import re
import sys

import customtkinter as ctk

from . import settings as cfg
from . import theme as T
from . import translators as tr
from .autostart import sync as sync_autostart
from .screen import work_area
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

# Logical (pre-DPI) geometry width for settings.
_WIN_W = 440


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, master: ctk.CTk) -> None:
        super().__init__(master)
        self.title(T.APP_NAME)
        # Position off-screen so layout works but user sees nothing
        self.geometry(f"{_WIN_W}x1200+-9999+-9999")
        self.minsize(400, 280)
        self.configure(fg_color=T.SETTINGS_BG)
        self.resizable(False, False)
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
            self,
            text="настройки",
            font=ui_font(17, "bold"),
            text_color=T.INK,
        ).pack(anchor="w", padx=pad, pady=(8, 4))

        card = ctk.CTkFrame(
            self,
            fg_color=T.SETTINGS_CARD,
            corner_radius=T.CORNER,
            border_width=1,
            border_color=T.LINE,
        )
        card.pack(fill="x", padx=pad, pady=(0, 6))
        inner_pad = T.INSET

        switch_kw = dict(
            text_color=T.INK,
            font=ui_font(12),
            progress_color=T.SWITCH_ON,
            button_color=T.SWITCH_KNOB,
            button_hover_color=T.SWITCH_KNOB_HOVER,
            fg_color=T.SWITCH_OFF,
            command=self._apply_switches,
        )

        self._instant = ctk.CTkSwitch(
            card, text="мгновенный перевод при вставке", **switch_kw
        )
        self._instant.pack(anchor="w", padx=inner_pad, pady=(inner_pad, 4))
        if s.instant_translate:
            self._instant.select()

        self._chivo = ctk.CTkSwitch(
            card, text="чивобля? при выделении текста", **switch_kw
        )
        self._chivo.pack(anchor="w", padx=inner_pad, pady=4)
        if s.chivoblya_enabled:
            self._chivo.select()

        self._autostart = ctk.CTkSwitch(
            card, text="запускать вместе с Windows", **switch_kw
        )
        self._autostart.pack(anchor="w", padx=inner_pad, pady=(0, 4))
        if s.autostart:
            self._autostart.select()
        if sys.platform != "win32":
            self._autostart.configure(state="disabled")

        self._close_tray = ctk.CTkSwitch(
            card, text="закрытие окна — в трей", **switch_kw
        )
        self._close_tray.pack(anchor="w", padx=inner_pad, pady=(0, 4))
        if s.close_to_tray:
            self._close_tray.select()

        trow = ctk.CTkFrame(card, fg_color="transparent")
        trow.pack(fill="x", padx=inner_pad, pady=(6, 2))
        ctk.CTkLabel(
            trow, text="тема", text_color=T.INK_FAINT, font=ui_font(11)
        ).pack(anchor="w")
        theme_row = ctk.CTkFrame(trow, fg_color="transparent")
        theme_row.pack(anchor="w", pady=(4, 0))
        for i, key in enumerate(T.THEME_CHOICES):
            self._theme_btns[key] = self._theme_btn(
                theme_row,
                key,
                T.THEME_LABELS[key],
                side="left",
                padx=(0, 8) if i < len(T.THEME_CHOICES) - 1 else (0, 0),
            )
        self._sync_theme_buttons()

        prow = ctk.CTkFrame(card, fg_color="transparent")
        prow.pack(fill="x", padx=inner_pad, pady=(6, 2))
        ctk.CTkLabel(
            prow, text="провайдер", text_color=T.INK_FAINT, font=ui_font(11)
        ).pack(anchor="w")
        labels = [label for _, label, _ in tr.list_providers()]
        self._pmap = {label: pid for pid, label, _ in tr.list_providers()}
        self._pinv = {pid: label for pid, label, _ in tr.list_providers()}
        self._prov = ctk.CTkComboBox(
            prow,
            values=labels,
            width=220,
            height=T.CTRL_H,
            command=lambda _v: self._apply_switches(),
            fg_color=T.FIELD,
            border_color=T.LINE,
            button_color=T.LINE_STRONG,
            button_hover_color=T.INK_SOFT,
            text_color=T.INK,
            dropdown_fg_color=T.SURFACE,
            dropdown_text_color=T.INK,
            font=ui_font(12),
        )
        self._prov.set(self._pinv.get(s.provider_id, labels[0]))
        self._prov.pack(anchor="w", pady=(3, 0))
        tune_combobox(self._prov)

        sep = ctk.CTkFrame(card, fg_color=T.LINE, height=1)
        sep.pack(fill="x", padx=inner_pad, pady=8)

        ctk.CTkLabel(
            card,
            text="горячая клавиша перевода",
            text_color=T.INK,
            font=ui_font(12, "bold"),
        ).pack(anchor="w", padx=inner_pad)

        mode_row = ctk.CTkFrame(card, fg_color="transparent")
        mode_row.pack(anchor="w", padx=inner_pad, pady=(6, 4))
        self._mode_btns[_MODE_DOUBLE] = self._mode_btn(
            mode_row, _MODE_DOUBLE, side="left", padx=(0, 8)
        )
        self._mode_btns[_MODE_COMBO] = self._mode_btn(
            mode_row, _MODE_COMBO, side="left"
        )
        self._sync_mode_buttons()

        self._hk_label = ctk.CTkLabel(
            card,
            text=self._hk.label(),
            text_color=T.INK,
            font=ui_font(14, "bold"),
        )
        self._hk_label.pack(anchor="w", padx=inner_pad, pady=(0, 2))

        self._hk_hint = ctk.CTkLabel(
            card,
            text=" ",
            text_color=T.INK_FAINT,
            font=ui_font(10),
            wraplength=360,
            justify="left",
            height=16,
        )
        self._hk_hint.pack(anchor="w", padx=inner_pad, pady=(0, 2))

        brow = ctk.CTkFrame(card, fg_color="transparent")
        brow.pack(fill="x", padx=inner_pad, pady=(0, inner_pad))
        self._btn_rec = ctk.CTkButton(
            brow,
            text="записать…",
            width=112,
            height=T.ROW_H,
            corner_radius=T.ROW_H // 2,
            fg_color=T.ACCENT,
            hover_color=T.ACCENT_HOVER,
            text_color=T.ON_ACCENT,
            font=ui_font(12),
            command=self._start_capture,
        )
        self._btn_rec.pack(side="left")
        ctk.CTkButton(
            brow,
            text="сброс Ctrl+Alt+E",
            width=128,
            height=T.ROW_H,
            corner_radius=T.ROW_H // 2,
            fg_color=T.SURFACE,
            border_width=1,
            border_color=T.LINE,
            hover_color=T.CHIP_HOVER,
            text_color=T.INK,
            font=ui_font(11),
            command=self._reset_hotkey,
        ).pack(side="left", padx=(8, 0))

        ctk.CTkFrame(card, fg_color=T.LINE, height=1).pack(
            fill="x", padx=inner_pad, pady=(0, 8)
        )
        self._build_acronyms(card, inner_pad, switch_kw)

        ctk.CTkFrame(card, fg_color=T.LINE, height=1).pack(
            fill="x", padx=inner_pad, pady=(0, 8)
        )
        self._build_ai(card, inner_pad, switch_kw)

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=pad, pady=(0, 6))
        self._status = ctk.CTkLabel(
            foot, text="", text_color=T.INK_FAINT, font=ui_font(10)
        )
        self._status.pack(side="left")
        ctk.CTkButton(
            foot,
            text="закрыть",
            width=96,
            height=T.ROW_H,
            corner_radius=T.ROW_H // 2,
            fg_color=T.ACCENT,
            hover_color=T.ACCENT_HOVER,
            text_color=T.ON_ACCENT,
            font=ui_font(12),
            command=self._close,
        ).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after_idle(lambda: self._measure_and_show(0))

    def _content_bottom(self) -> int:
        bottom = 0
        for ch in self.winfo_children():
            try:
                bottom = max(bottom, int(ch.winfo_y()) + int(ch.winfo_height()))
            except Exception:
                pass
        return bottom


    def _measure_and_show(self, attempt: int = 0) -> None:
        """Measure content while hidden, set final size, center, then show."""
        try:
            # Seed tall off-screen so pack lays out all children unconstrained
            self.geometry(f"{_WIN_W}x1200+-9999+-9999")
            self.update_idletasks()
        except Exception:
            return
        bottom = self._content_bottom()
        if bottom < 80 and attempt < 25:
            self.after(20, lambda: self._measure_and_show(attempt + 1))
            return
        # content_bottom is in physical (DPI-scaled) pixels,
        # but geometry() takes logical units. Compute the DPI scale
        # from the seeded window: winfo_height (physical) / 1200 (logical).
        phys_h = max(int(self.winfo_height()), 1)
        scale = phys_h / 1200.0
        if scale < 0.5 or scale > 4.0:
            scale = 1.0
        # Convert physical content height to logical geometry units
        measured = max(int(round((bottom + 12) / scale)), 300)
        # Cap to 92% of work area (work_area returns physical pixels)
        try:
            _wx, _wy, _ww, wah = work_area()
            cap = max(int(round(wah * 0.92 / scale)), 300)
            if measured > cap:
                measured = cap
        except Exception:
            pass
        self.geometry(f"{_WIN_W}x{measured}")
        self.minsize(400, min(280, measured))
        self.update_idletasks()
        self._center_on_parent()
        self.lift()
        self.focus_force()

    def _center_on_parent(self) -> None:
        try:
            self.update_idletasks()
            ww = int(self.winfo_width())
            wh = int(self.winfo_height())
            wx, wy, aw, ah = work_area()
            # Try to center over parent window
            master = self.master
            use_parent = False
            if master is not None:
                try:
                    mw = int(master.winfo_width())
                    mh = int(master.winfo_height())
                    # Only use parent coords if it is actually visible (not in tray)
                    if mw > 1 and mh > 1 and str(master.state()) != "withdrawn":
                        mx = int(master.winfo_rootx())
                        my = int(master.winfo_rooty())
                        x = mx + (mw - ww) // 2
                        y = my + (mh - wh) // 2
                        use_parent = True
                except Exception:
                    pass
            if not use_parent:
                # Fallback: center on screen
                x = wx + (aw - ww) // 2
                y = wy + (ah - wh) // 2
            # Clamp to work area
            x = max(wx, min(x, wx + aw - ww))
            y = max(wy, min(y, wy + ah - wh))
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _theme_btn(
        self,
        parent,
        key: str,
        label: str,
        *,
        side: str,
        padx: tuple[int, int] = (0, 0),
    ) -> ctk.CTkButton:
        btn = ctk.CTkButton(
            parent,
            text=label,
            width=88,
            height=T.ROW_H,
            corner_radius=T.ROW_H // 2,
            fg_color=T.SURFACE,
            border_width=1,
            border_color=T.LINE,
            hover_color=T.CHIP_HOVER,
            text_color=T.INK,
            font=ui_font(11),
            command=lambda k=key: self._on_theme(k),
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

    def _mode_btn(
        self, parent, label: str, *, side: str, padx: tuple[int, int] = (0, 0)
    ) -> ctk.CTkButton:
        mode = "double" if label == _MODE_DOUBLE else "combo"

        def pick() -> None:
            self._on_mode(mode)

        btn = ctk.CTkButton(
            parent,
            text=label,
            width=148 if mode == "double" else 120,
            height=T.ROW_H,
            corner_radius=T.ROW_H // 2,
            fg_color=T.SURFACE,
            border_width=1,
            border_color=T.LINE,
            hover_color=T.CHIP_HOVER,
            text_color=T.INK,
            font=ui_font(11),
            command=pick,
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
            scan_code=self._hk.scan_code,
            ctrl=self._hk.ctrl,
            shift=self._hk.shift,
            alt=self._hk.alt,
            win=self._hk.win,
            mode=mode,
        )
        self._sync_mode_buttons()
        self._hk_label.configure(text=self._hk.label())
        self._try_save_hotkey()

    def _reset_hotkey(self) -> None:
        self._stop_capture()
        self._hk = HotkeySpec()
        self._sync_mode_buttons()
        self._hk_label.configure(text=self._hk.label())
        self._hk_hint.configure(
            text="сброшено на Ctrl+Alt+E (как Crow)", text_color=T.INK_FAINT
        )
        self._try_save_hotkey()

    def _start_capture(self) -> None:
        if keyboard is None:
            self._hk_hint.configure(
                text="пакет keyboard не установлен", text_color=T.ERR
            )
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
                "ctrl",
                "left ctrl",
                "right ctrl",
                "shift",
                "left shift",
                "right shift",
                "alt",
                "left alt",
                "right alt",
                "windows",
                "left windows",
                "right windows",
                "cmd",
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

            spec = HotkeySpec(
                scan_code=sc,
                ctrl=ctrl,
                shift=shift,
                alt=alt,
                win=win,
                mode=mode,
            )
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
            show_examples=False,
            provider_id=pid,
            ui_theme=self._ui_theme,
        )
        ok, err = sync_autostart(want_autostart)
        if not ok:
            self._status.configure(text=(err or "автозапуск не применился")[:48])
            return
        self._status.configure(text="сохранено")

    # ── acronyms ──────────────────────────────────────────────────────────
    def _build_acronyms(self, card, inner_pad: int, switch_kw: dict) -> None:
        """Toggle + exactly which dictionaries are loaded and from where."""
        from . import acronyms

        head = ctk.CTkFrame(card, fg_color="transparent", height=T.BAR_H)
        head.pack(fill="x", padx=inner_pad)
        head.pack_propagate(False)
        ctk.CTkLabel(
            head, text="акронимы", text_color=T.INK, font=ui_font(12, "bold")
        ).pack(side="left")
        btn_kw = dict(
            height=T.CTRL_H,
            corner_radius=T.CORNER_SM,
            fg_color=T.SURFACE,
            border_width=1,
            border_color=T.LINE,
            hover_color=T.CHIP_HOVER,
            text_color=T.INK_SOFT,
            font=ui_font(11),
        )
        ctk.CTkButton(
            head, text="папка паков", width=96, command=self._open_packs_dir, **btn_kw
        ).pack(side="right")
        ctk.CTkButton(
            head, text="словарь…", width=84, command=self._open_dictionary, **btn_kw
        ).pack(side="right", padx=(0, 6))

        self._acro_on = ctk.CTkSwitch(
            card,
            text="разбирать акронимы в главном окне",
            **dict(switch_kw, command=self._apply_acronyms),
        )
        self._acro_on.pack(anchor="w", padx=inner_pad, pady=(4, 6))
        if cfg.get().acronyms_enabled:
            self._acro_on.select()

        self._pack_boxes: dict[str, ctk.CTkCheckBox] = {}
        listing = ctk.CTkFrame(
            card,
            fg_color=T.FIELD,
            corner_radius=T.CORNER_SM,
            border_width=1,
            border_color=T.LINE,
        )
        listing.pack(fill="x", padx=inner_pad, pady=(0, inner_pad))

        found = acronyms.packs()
        if not found:
            ctk.CTkLabel(
                listing,
                text="словарей нет",
                text_color=T.INK_FAINT,
                font=ui_font(11),
            ).pack(anchor="w", padx=8, pady=6)
        for i, p in enumerate(found):
            where = "локально" if p.origin == "local" else "в репо"
            pady = (6, 3) if i == 0 else (0, 3 if i < len(found) - 1 else 6)
            if p.error:
                ctk.CTkLabel(
                    listing,
                    text=f"{p.id} · не читается",
                    text_color=T.ERR,
                    font=ui_font(11),
                ).pack(anchor="w", padx=8, pady=pady)
                continue
            cb = ctk.CTkCheckBox(
                listing,
                text=f"{p.title} · {p.count} · {where}",
                width=20,
                checkbox_width=16,
                checkbox_height=16,
                corner_radius=3,
                border_width=1,
                fg_color=T.SWITCH_ON,
                hover_color=T.SWITCH_ON,
                border_color=T.LINE_STRONG,
                checkmark_color=T.SURFACE,
                text_color=T.INK,
                font=ui_font(11),
                command=self._apply_acronyms,
            )
            cb.pack(anchor="w", padx=8, pady=pady)
            if acronyms.is_enabled(p.id):
                cb.select()
            self._pack_boxes[p.id] = cb

    # ── AI helper ─────────────────────────────────────────────────────────
    def _build_ai(self, card, inner_pad: int, switch_kw: dict) -> None:
        """Switch, model, and a plain answer to «why are the buttons grey»."""
        from . import ai_config, ai_token

        ctk.CTkLabel(
            card, text="ИИ-помощник", text_color=T.INK, font=ui_font(12, "bold")
        ).pack(anchor="w", padx=inner_pad)

        self._ai_on = ctk.CTkSwitch(
            card,
            text="кнопки «причесать» и «объясни» в главном окне",
            **dict(switch_kw, command=self._apply_ai),
        )
        self._ai_on.pack(anchor="w", padx=inner_pad, pady=(4, 6))
        if cfg.get().ai_enabled:
            self._ai_on.select()

        mrow = ctk.CTkFrame(card, fg_color="transparent")
        mrow.pack(fill="x", padx=inner_pad, pady=(0, 4))
        ctk.CTkLabel(mrow, text="модель", text_color=T.INK_FAINT, font=ui_font(11)).pack(
            anchor="w"
        )
        # empty string = whatever ai.json says, so the config stays the default
        self._ai_default = f"как в ai.json ({ai_config.model() or '—'})"
        self._ai_model = ctk.CTkComboBox(
            mrow,
            values=[self._ai_default, *ai_config.models()],
            width=260,
            height=T.CTRL_H,
            command=lambda _v: self._apply_ai(),
            fg_color=T.FIELD,
            border_color=T.LINE,
            button_color=T.LINE_STRONG,
            button_hover_color=T.INK_SOFT,
            text_color=T.INK,
            dropdown_fg_color=T.SURFACE,
            dropdown_text_color=T.INK,
            font=ui_font(12),
        )
        self._ai_model.set(cfg.get().ai_model or self._ai_default)
        self._ai_model.pack(anchor="w", pady=(3, 0))
        tune_combobox(self._ai_model)

        self._ai_state = ctk.CTkLabel(
            card,
            text="",
            text_color=T.INK_FAINT,
            font=ui_font(10),
            anchor="w",
            justify="left",
            wraplength=420,
        )
        self._ai_state.pack(anchor="w", padx=inner_pad, pady=(6, inner_pad))
        self._sync_ai_state()
        ai_token.on_change(self._on_ai_token)

    def _sync_ai_state(self) -> None:
        from . import ai_config, ai_token

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
            pass  # window already closed

    def _apply_ai(self) -> None:
        picked = self._ai_model.get()
        cfg.update(
            ai_enabled=bool(self._ai_on.get()),
            ai_model="" if picked == self._ai_default else picked,
        )
        self._status.configure(text="ИИ · применено")

    def _apply_acronyms(self) -> None:
        cfg.update(
            acronyms_enabled=bool(self._acro_on.get()),
            acronym_packs={pid: bool(cb.get()) for pid, cb in self._pack_boxes.items()},
        )
        self._status.configure(text="словари · применено")

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
