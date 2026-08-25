"""CTk widget tweaks — work around CustomTkinter layout quirks."""

from __future__ import annotations

import customtkinter as ctk

from . import theme as T


def tune_combobox(
    combo: ctk.CTkComboBox, *, left_pad: int = 8, right_extra: int = 2
) -> None:
    """Fix clipped text in CTkComboBox (rounded canvas vs Entry padx)."""
    combo.configure(
        corner_radius=T.CORNER_SM,
        state="readonly",
        justify="left",
    )

    def apply() -> None:
        try:
            h = int(getattr(combo, "_current_height", combo.cget("height") or T.ROW_H))
            right_pad = h + right_extra
            scale = getattr(combo, "_apply_widget_scaling", lambda x: x)
            combo._entry.grid_configure(
                padx=(scale(left_pad), scale(right_pad)),
            )
        except Exception:  # noqa: BLE001
            pass

    def on_configure(_event=None) -> None:
        combo.after_idle(apply)

    combo.after(0, apply)
    combo.bind("<Configure>", on_configure, add="+")
