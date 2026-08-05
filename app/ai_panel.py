"""Strip under the panes for whatever the AI said that is not the answer itself.

«причесать» puts the English in the target pane — the same place a translation
lands — and the Russian back-translation plus the «why it reads better» note
here. «объясни» has no English half, so the whole answer lives here.

Same shape as `acro_panel.AcronymPanel`: full width, sized to content, capped at
a third of the window, gone entirely when there is nothing to show.
"""

from __future__ import annotations

import customtkinter as ctk

from . import theme as T
from .theme import ui_font

MAX_FRACTION = 0.35
MIN_H = 46
INDENT = 18


class AiPanel(ctk.CTkFrame):
    """`show_polish(...)` / `show_text(...)` fill it; `hide()` takes it away."""

    def __init__(self, parent) -> None:
        super().__init__(
            parent,
            fg_color=T.SURFACE,
            corner_radius=T.CORNER,
            border_width=1,
            border_color=T.LINE,
        )
        self._pack_kw = dict(fill="x", pady=(T.GAP, 0))
        self._shown = False
        self._rows: list[int] = []
        self._blocks = 0

        self._f_body = ui_font(12)
        self._f_small = ui_font(11)

        bar = ctk.CTkFrame(self, fg_color="transparent", height=T.BAR_H)
        bar.pack(fill="x", padx=T.INSET, pady=(T.INSET, T.BAR_GAP))
        bar.pack_propagate(False)

        self._title = ctk.CTkLabel(
            bar, text="ИИ", font=ui_font(11), text_color=T.INK_FAINT, anchor="w"
        )
        self._title.pack(side="left")

        ctk.CTkButton(
            bar,
            text="скрыть",
            width=64,
            height=T.CTRL_H,
            corner_radius=T.CORNER_SM,
            fg_color=T.CHIP_BG,
            border_width=1,
            border_color=T.LINE,
            hover_color=T.CHIP_HOVER,
            text_color=T.INK_SOFT,
            font=ui_font(11),
            command=self.hide,
        ).pack(side="right")

        self._box = ctk.CTkTextbox(
            self,
            fg_color=T.FIELD,
            text_color=T.INK,
            border_width=1,
            border_color=T.LINE,
            border_spacing=T.TEXT_BORDER_SPACING,
            font=self._f_body,
            wrap="word",
            height=MIN_H,
            corner_radius=T.CORNER_SM,
            scrollbar_button_color=T.LINE,
            scrollbar_button_hover_color=T.LINE_STRONG,
        )
        self._box.pack(fill="x", padx=T.INSET, pady=(0, T.INSET))
        self._inner = getattr(self._box, "_textbox", self._box)
        self._make_tags()
        self._box.configure(state="disabled")
        self._last_w = 0
        self._fit_job: str | None = None
        self.bind("<Configure>", self._on_resize)

    def _on_resize(self, event) -> None:
        if not self._shown or abs(event.width - self._last_w) < 24:
            return
        self._last_w = event.width
        if self._fit_job is not None:
            try:
                self.after_cancel(self._fit_job)
            except Exception:  # noqa: BLE001
                pass
        self._fit_job = self.after(150, lambda: self._fit(retry=False))

    # ── visibility ───────────────────────────────────────────

    def show(self) -> None:
        if not self._shown:
            self.pack(**self._pack_kw)
            self._shown = True

    def hide(self) -> None:
        if self._shown:
            self.pack_forget()
            self._shown = False

    # ── styling ──────────────────────────────────────────────

    def _font(self, f):
        try:
            return self._box._apply_font_scaling(f)
        except Exception:  # noqa: BLE001
            return (T.FONT_UI, f.cget("size"))

    def _make_tags(self) -> None:
        t = self._inner
        t.tag_config("lead", font=self._font(self._f_small), foreground=T.INK_FAINT, spacing1=6)
        t.tag_config("body", font=self._font(self._f_body), foreground=T.INK,
                     lmargin1=INDENT, lmargin2=INDENT)
        t.tag_config("note", font=self._font(self._f_small), foreground=T.INK_SOFT,
                     lmargin1=INDENT, lmargin2=INDENT)
        t.tag_config("wait", font=self._font(self._f_small), foreground=T.INK_FAINT)
        t.tag_config("err", font=self._font(self._f_small), foreground=T.ERR)

    # ── writing ──────────────────────────────────────────────

    def _line(self, text: str, tag: str, size: int) -> None:
        for i, part in enumerate((text or "").splitlines() or [""]):
            self._inner.insert("end", part + "\n", tag)
            self._rows.append(size)

    def _begin(self, title: str) -> None:
        self._rows = []
        self._blocks = 0
        self._box.configure(state="normal")
        self._inner.delete("1.0", "end")
        self._title.configure(text=title)

    def _end(self) -> None:
        self._inner.delete("end-1c", "end")
        self._box.configure(state="disabled")
        self.show()
        self._fit()

    # ── public ───────────────────────────────────────────────

    def show_polish(self, russian: str, why: str) -> None:
        """The English is already in the target pane; this is the rest of it."""
        if not (russian or "").strip() and not (why or "").strip():
            self.hide()
            return
        self._begin("ИИ · причесал")
        if russian.strip():
            self._blocks += 1
            self._line("по-русски", "lead", 11)
            self._line(russian.strip(), "body", 12)
        if why.strip():
            self._blocks += 1
            self._line("почему так лучше", "lead", 11)
            self._line(why.strip(), "note", 11)
        self._end()

    def show_text(self, title: str, text: str) -> None:
        """One block of plain Russian — «объясни» and nothing else."""
        if not (text or "").strip():
            self.hide()
            return
        self._begin(title)
        self._blocks += 1
        self._line(text.strip(), "body", 12)
        self._end()

    def show_wait(self, message: str) -> None:
        self._begin("ИИ")
        self._line(message, "wait", 11)
        self._end()

    def show_error(self, message: str) -> None:
        self._begin("ИИ")
        self._line(f"не вышло: {message}", "err", 11)
        self._end()

    # ── sizing ───────────────────────────────────────────────

    def _fit(self, retry: bool = True) -> None:
        if not self._shown:
            return
        try:
            self.update_idletasks()
        except Exception:  # noqa: BLE001
            pass

        px = {}
        for size, f in ((12, self._f_body), (11, self._f_small)):
            try:
                px[size] = int(f.metrics("linespace"))
            except Exception:  # noqa: BLE001
                px[size] = size + 5
        need = sum(px.get(s, 17) for s in self._rows) + self._blocks * 6

        # Same trap as the acronym strip: an unmapped Text is one char wide.
        if self._inner.winfo_width() > 50:
            try:
                shown = int(self._inner.count("1.0", "end-1c", "displaylines")[0]) + 1
                need += max(0, shown - len(self._rows)) * px[12]
            except Exception:  # noqa: BLE001
                pass
        elif retry:
            self.after_idle(lambda: self._fit(retry=False))

        need += 2 * T.TEXT_BORDER_SPACING + 4
        self._box.configure(height=max(MIN_H, min(need, self._cap())))

    def _cap(self) -> int:
        try:
            phys = int(self.winfo_toplevel().winfo_height())
            scale = float(ctk.ScalingTracker.get_widget_scaling(self)) or 1.0
            logical = phys / scale
        except Exception:  # noqa: BLE001
            logical = 0
        if logical < 200:
            logical = 560
        return max(MIN_H, int(logical * MAX_FRACTION))
