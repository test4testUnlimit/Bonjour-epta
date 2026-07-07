"""Settings — live apply; interactive hotkey capture."""

from __future__ import annotations

import customtkinter as ctk

from . import settings as cfg
from . import theme as T
from . import translators as tr
from .win_hotkeys import HotkeySpec, check_reserved

try:
    import keyboard
except ImportError:  # pragma: no cover
    keyboard = None  # type: ignore


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, master: ctk.CTk) -> None:
        super().__init__(master)
        self.title(T.APP_NAME)  # short; no duplicate long chrome
        self.geometry("480x520")
        self.minsize(440, 480)
        self.configure(fg_color=T.BG)
        self.resizable(False, False)
        self.transient(master)

        self._capture_hook = None
        self._pending: HotkeySpec | None = None
        s = cfg.get()
        self._hk = s.hotkey_spec()

        from .theme import ui_font

        ctk.CTkLabel(
            self,
            text="настройки",
            font=ui_font(20),
            text_color=T.INK,
        ).pack(anchor="w", padx=24, pady=(20, 2))
        ctk.CTkLabel(
            self,
            text="сразу, без перезапуска · epta = ёпта",
            text_color=T.INK_FAINT,
            font=ui_font(12),
        ).pack(anchor="w", padx=24, pady=(0, 12))

        card = ctk.CTkFrame(
            self, fg_color=T.SURFACE, corner_radius=14, border_width=1, border_color=T.LINE
        )
        card.pack(fill="both", expand=True, padx=24, pady=(0, 10))

        self._instant = ctk.CTkSwitch(
            card,
            text="мгновенный перевод при вставке",
            text_color=T.INK,
            progress_color=T.ACCENT,
            button_color=T.SURFACE,
            button_hover_color=T.CHIP_HOVER,
            fg_color=T.LINE_STRONG,
            command=self._apply_switches,
        )
        self._instant.pack(anchor="w", padx=18, pady=(16, 8))
        if s.instant_translate:
            self._instant.select()

        self._chivo = ctk.CTkSwitch(
            card,
            text="чивобля? при выделении текста",
            text_color=T.INK,
            progress_color=T.ACCENT,
            button_color=T.SURFACE,
            button_hover_color=T.CHIP_HOVER,
            fg_color=T.LINE_STRONG,
            command=self._apply_switches,
        )
        self._chivo.pack(anchor="w", padx=18, pady=8)
        if s.chivoblya_enabled:
            self._chivo.select()

        # provider
        prow = ctk.CTkFrame(card, fg_color="transparent")
        prow.pack(fill="x", padx=18, pady=(10, 8))
        ctk.CTkLabel(prow, text="провайдер", text_color=T.INK_FAINT).pack(anchor="w")
        labels = [label for _, label, _ in tr.list_providers()]
        self._pmap = {label: pid for pid, label, _ in tr.list_providers()}
        self._pinv = {pid: label for pid, label, _ in tr.list_providers()}
        self._prov = ctk.CTkComboBox(
            prow,
            values=labels,
            width=240,
            command=lambda _v: self._apply_switches(),
            fg_color=T.FIELD,
            border_color=T.LINE,
            button_color=T.LINE_STRONG,
            text_color=T.INK,
            dropdown_fg_color=T.SURFACE,
        )
        self._prov.set(self._pinv.get(s.provider_id, labels[0]))
        self._prov.pack(anchor="w", pady=(6, 0))

        # hotkey block
        sep = ctk.CTkFrame(card, fg_color=T.LINE, height=1)
        sep.pack(fill="x", padx=18, pady=14)

        ctk.CTkLabel(
            card,
            text="горячая клавиша перевода",
            text_color=T.INK,
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=18)

        self._mode = ctk.CTkSegmentedButton(
            card,
            values=["двойное нажатие", "комбинация"],
            command=self._on_mode,
            fg_color=T.CHIP_BG,
            selected_color=T.ACCENT,
            selected_hover_color=T.ACCENT_HOVER,
            unselected_color=T.CHIP_BG,
            unselected_hover_color=T.CHIP_HOVER,
            text_color=T.INK,
            text_color_disabled=T.INK_FAINT,
        )
        self._mode.pack(anchor="w", padx=18, pady=(8, 6))
        self._mode.set("двойное нажатие" if self._hk.mode == "double" else "комбинация")

        self._hk_label = ctk.CTkLabel(
            card,
            text=self._hk.label(),
            text_color=T.INK,
            font=ctk.CTkFont(family="Consolas", size=16),
        )
        self._hk_label.pack(anchor="w", padx=18, pady=(4, 4))

        self._hk_hint = ctk.CTkLabel(
            card,
            text="нажмите «записать» и свою комбинацию",
            text_color=T.INK_FAINT,
            font=ctk.CTkFont(size=11),
            wraplength=400,
            justify="left",
        )
        self._hk_hint.pack(anchor="w", padx=18, pady=(0, 8))

        brow = ctk.CTkFrame(card, fg_color="transparent")
        brow.pack(fill="x", padx=18, pady=(0, 16))
        self._btn_rec = ctk.CTkButton(
            brow,
            text="записать…",
            width=120,
            height=34,
            corner_radius=17,
            fg_color=T.ACCENT,
            hover_color=T.ACCENT_HOVER,
            text_color="#fff",
            command=self._start_capture,
        )
        self._btn_rec.pack(side="left")
        ctk.CTkButton(
            brow,
            text="сброс Ctrl+Alt+E",
            width=130,
            height=34,
            corner_radius=17,
            fg_color=T.SURFACE,
            border_width=1,
            border_color=T.LINE,
            hover_color=T.CHIP_HOVER,
            text_color=T.INK,
            command=self._reset_hotkey,
        ).pack(side="left", padx=8)

        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.pack(fill="x", padx=24, pady=(0, 16))
        self._status = ctk.CTkLabel(foot, text="", text_color=T.INK_FAINT, font=ctk.CTkFont(size=11))
        self._status.pack(side="left")
        ctk.CTkButton(
            foot,
            text="закрыть",
            width=100,
            height=34,
            corner_radius=17,
            fg_color=T.ACCENT,
            hover_color=T.ACCENT_HOVER,
            text_color="#ffffff",
            command=self._close,
        ).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._close)

    def _on_mode(self, value: str) -> None:
        mode = "double" if value.startswith("двойн") else "combo"
        self._hk = HotkeySpec(
            scan_code=self._hk.scan_code,
            ctrl=self._hk.ctrl,
            shift=self._hk.shift,
            alt=self._hk.alt,
            win=self._hk.win,
            mode=mode,
        )
        self._hk_label.configure(text=self._hk.label())
        self._try_save_hotkey()

    def _reset_hotkey(self) -> None:
        self._stop_capture()
        self._hk = HotkeySpec()  # Crow default Ctrl+Alt+E
        self._mode.set("комбинация")
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
            text="слушаю: Ctrl / Shift / Alt / Win + клавиша (или просто клавиша для ×2)",
            text_color=T.INK,
        )

        def on_event(event: object) -> None:
            if getattr(event, "event_type", None) != "down":
                return
            name = str(getattr(event, "name", "") or "").lower()
            # skip pure modifiers as the trigger key
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
                # live mod display
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
            # if user chose combo mode in UI but pressed bare key, keep UI mode
            ui_mode = "double" if self._mode.get().startswith("двойн") else "combo"
            if ui_mode == "combo" and not (ctrl or shift or alt or win):
                # bare key in combo mode — still record as combo without mods (will fail reserved check)
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
        self._mode.set("двойное нажатие" if spec.mode == "double" else "комбинация")
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
        cfg.update(
            instant_translate=bool(self._instant.get()),
            chivoblya_enabled=bool(self._chivo.get()),
            show_examples=False,
            provider_id=pid,
        )
        self._status.configure(text="сохранено")

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
        self._stop_capture()
        self.destroy()
