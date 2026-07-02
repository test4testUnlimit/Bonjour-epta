"""Main dual-pane translator window."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk
import pyperclip

from . import languages as langs
from . import translators as tr

# Dark modern palette — not generic purple AI sludge
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

BG = "#0f1419"
PANEL = "#1a2332"
BORDER = "#2d3a4f"
ACCENT = "#3d9cf0"
ACCENT_DIM = "#2a6aa8"
TEXT = "#e7ecf3"
MUTED = "#8b9bb4"
SUCCESS = "#3ecf8e"
ERR = "#f07178"


class TranslatorApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Bonjur-epta")
        self.geometry("980x560")
        self.minsize(720, 420)
        self.configure(fg_color=BG)

        self._source_lang = ctk.StringVar(value="auto")
        self._target_lang = ctk.StringVar(value="ru")
        self._provider = ctk.StringVar(value=tr.DEFAULT_PROVIDER_ID)
        self._status = ctk.StringVar(value="Готов")
        self._busy = False
        self._pending_source: str | None = None

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── layout ──────────────────────────────────────────────
    def _build(self) -> None:
        top = ctk.CTkFrame(self, fg_color=BG, height=48)
        top.pack(fill="x", padx=12, pady=(12, 6))
        top.pack_propagate(False)

        ctk.CTkLabel(
            top,
            text="Bonjur-epta",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color=TEXT,
        ).pack(side="left", padx=(4, 16))

        ctk.CTkLabel(top, text="API", text_color=MUTED, font=ctk.CTkFont(size=12)).pack(
            side="left", padx=(0, 6)
        )
        provider_labels = [f"{label}" for _, label, _ in tr.list_providers()]
        self._provider_ids = [pid for pid, _, _ in tr.list_providers()]
        self._provider_map = {label: pid for pid, label, _ in tr.list_providers()}
        default_label = next(
            label for pid, label, _ in tr.list_providers() if pid == tr.DEFAULT_PROVIDER_ID
        )
        self._provider_combo = ctk.CTkComboBox(
            top,
            values=provider_labels,
            width=160,
            command=self._on_provider_ui,
            fg_color=PANEL,
            border_color=BORDER,
            button_color=ACCENT_DIM,
            button_hover_color=ACCENT,
        )
        self._provider_combo.set(default_label)
        self._provider_combo.pack(side="left", padx=(0, 12))

        self._btn_translate = ctk.CTkButton(
            top,
            text="Перевести",
            width=110,
            fg_color=ACCENT,
            hover_color=ACCENT_DIM,
            command=self.translate_now,
        )
        self._btn_translate.pack(side="left", padx=4)

        self._btn_paste = ctk.CTkButton(
            top,
            text="Вставить",
            width=100,
            fg_color=PANEL,
            border_width=1,
            border_color=BORDER,
            hover_color=BORDER,
            command=self.paste_clipboard,
        )
        self._btn_paste.pack(side="left", padx=4)

        ctk.CTkLabel(top, textvariable=self._status, text_color=MUTED).pack(
            side="right", padx=8
        )

        body = ctk.CTkFrame(self, fg_color=BG)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        body.grid_columnconfigure(0, weight=1, uniform="pane")
        body.grid_columnconfigure(1, weight=0)
        body.grid_columnconfigure(2, weight=1, uniform="pane")
        body.grid_rowconfigure(0, weight=1)

        self._left = self._make_pane(body, side="source")
        self._left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        mid = ctk.CTkFrame(body, fg_color=PANEL, width=56, corner_radius=10)
        mid.grid(row=0, column=1, sticky="ns", padx=4)
        mid.grid_propagate(False)

        ctk.CTkButton(
            mid,
            text="⇄",
            width=40,
            height=40,
            font=ctk.CTkFont(size=20),
            fg_color=ACCENT_DIM,
            hover_color=ACCENT,
            command=self.swap_direction,
        ).pack(pady=(80, 8), padx=8)

        # Reserved slot for future mid-bar actions
        ctk.CTkLabel(mid, text="", text_color=MUTED).pack(expand=True)

        self._right = self._make_pane(body, side="target")
        self._right.grid(row=0, column=2, sticky="nsew", padx=(4, 0))

        hint = ctk.CTkLabel(
            self,
            text="Выделение → «чивобля?» · двойной ` / ё → сразу в окно",
            text_color=MUTED,
            font=ctk.CTkFont(size=11),
        )
        hint.pack(pady=(0, 8))

    def _make_pane(self, parent: ctk.CTkFrame, side: str) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=12, border_width=1, border_color=BORDER)
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        bar = ctk.CTkFrame(frame, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))

        if side == "source":
            values = [langs.label_of(c) for c in langs.codes_for_source()]
            codes = langs.codes_for_source()
            self._src_codes = codes
            self._src_label_to_code = {langs.label_of(c): c for c in codes}
            self._src_combo = ctk.CTkComboBox(
                bar,
                values=values,
                width=160,
                command=lambda v: self._source_lang.set(self._src_label_to_code.get(v, "auto")),
                fg_color=BG,
                border_color=BORDER,
                button_color=ACCENT_DIM,
            )
            self._src_combo.set(langs.label_of("auto"))
            self._src_combo.pack(side="left")
            ctk.CTkLabel(bar, text="исходный", text_color=MUTED, font=ctk.CTkFont(size=11)).pack(
                side="left", padx=8
            )
            self._src_box = ctk.CTkTextbox(
                frame,
                fg_color=BG,
                text_color=TEXT,
                border_color=BORDER,
                border_width=1,
                font=ctk.CTkFont(family="Segoe UI", size=14),
                wrap="word",
            )
            self._src_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        else:
            values = [langs.label_of(c) for c in langs.codes_for_target()]
            codes = langs.codes_for_target()
            self._tgt_codes = codes
            self._tgt_label_to_code = {langs.label_of(c): c for c in codes}
            self._tgt_combo = ctk.CTkComboBox(
                bar,
                values=values,
                width=160,
                command=lambda v: self._target_lang.set(self._tgt_label_to_code.get(v, "ru")),
                fg_color=BG,
                border_color=BORDER,
                button_color=ACCENT_DIM,
            )
            self._tgt_combo.set(langs.label_of("ru"))
            self._tgt_combo.pack(side="left")
            ctk.CTkLabel(bar, text="перевод", text_color=MUTED, font=ctk.CTkFont(size=11)).pack(
                side="left", padx=8
            )
            self._tgt_box = ctk.CTkTextbox(
                frame,
                fg_color=BG,
                text_color=TEXT,
                border_color=BORDER,
                border_width=1,
                font=ctk.CTkFont(family="Segoe UI", size=14),
                wrap="word",
            )
            self._tgt_box.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        return frame

    # ── actions ─────────────────────────────────────────────
    def _on_provider_ui(self, label: str) -> None:
        self._provider.set(self._provider_map.get(label, tr.DEFAULT_PROVIDER_ID))

    def paste_clipboard(self) -> None:
        try:
            text = pyperclip.paste()
        except Exception:  # noqa: BLE001
            text = ""
        if text:
            self.set_source_text(text)
            self.translate_now()

    def set_source_text(self, text: str) -> None:
        self._src_box.delete("1.0", "end")
        self._src_box.insert("1.0", text)

    def get_source_text(self) -> str:
        return self._src_box.get("1.0", "end-1c")

    def set_target_text(self, text: str) -> None:
        self._tgt_box.delete("1.0", "end")
        self._tgt_box.insert("1.0", text)

    def swap_direction(self) -> None:
        src_text = self.get_source_text()
        tgt_text = self._tgt_box.get("1.0", "end-1c")
        src_code = self._source_lang.get()
        tgt_code = self._target_lang.get()

        # swap texts
        self.set_source_text(tgt_text)
        self.set_target_text(src_text)

        # swap langs (auto cannot be target)
        new_src = tgt_code
        new_tgt = src_code if src_code != "auto" else "en"
        self._source_lang.set(new_src)
        self._target_lang.set(new_tgt)
        self._src_combo.set(langs.label_of(new_src))
        self._tgt_combo.set(langs.label_of(new_tgt))

    def translate_now(self) -> None:
        if self._busy:
            return
        text = self.get_source_text().strip()
        if not text:
            self._status.set("Нет текста")
            return

        self._busy = True
        self._status.set("Перевод…")
        self._btn_translate.configure(state="disabled")

        source = self._source_lang.get()
        target = self._target_lang.get()
        provider_id = self._provider.get()

        def work() -> None:
            result = tr.translate(text, source=source, target=target, provider_id=provider_id)
            self.after(0, lambda: self._apply_result(result))

        threading.Thread(target=work, daemon=True).start()

    def _apply_result(self, result: tr.TranslateResult) -> None:
        self._busy = False
        self._btn_translate.configure(state="normal")
        if not result.ok:
            self._status.set(f"Ошибка: {result.error}")
            self.set_target_text("")
            return
        self.set_target_text(result.text)
        det = result.detected_source
        if det and self._source_lang.get() == "auto":
            self._status.set(f"OK · {result.provider} · detected: {det}")
        else:
            self._status.set(f"OK · {result.provider}")

    def bring_with_selection(self, text: str) -> None:
        """Called from hotkey path: fill source, show window, translate."""
        def ui() -> None:
            self.set_source_text(text)
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.after(80, lambda: self.attributes("-topmost", False))
            self.focus_force()
            self.translate_now()

        # ensure on UI thread
        self.after(0, ui)

    def _on_close(self) -> None:
        # Hide to tray-like behaviour later; for now just quit.
        self.destroy()


def run_app() -> TranslatorApp:
    app = TranslatorApp()
    return app
