"""Windows 11 reserved / system shortcut checks.

List distilled from Microsoft keyboard shortcuts docs
(https://support.microsoft.com/windows/keyboard-shortcuts-in-windows).
We block exact matches that steal global hooks or fight the shell.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HotkeySpec:
    """Physical key + modifiers (layout-independent via scan_code when set).

    Default matches Crow Translate: Ctrl+Alt+E (scan E = 18).
    """

    scan_code: int = 18  # E
    ctrl: bool = True
    shift: bool = False
    alt: bool = True
    win: bool = False
    # "double" = double-tap key
    # "combo" = single press with required modifiers (Crow path)
    mode: str = "combo"  # double | combo

    def label(self) -> str:
        parts: list[str] = []
        if self.ctrl:
            parts.append("Ctrl")
        if self.shift:
            parts.append("Shift")
        if self.alt:
            parts.append("Alt")
        if self.win:
            parts.append("Win")
        key = _scan_label(self.scan_code)
        if self.mode == "double":
            if parts:
                return "+".join(parts) + f"+{key} ×2"
            return f"{key} ×2"
        parts.append(key)
        return "+".join(parts)

    def to_dict(self) -> dict:
        return {
            "scan_code": self.scan_code,
            "ctrl": self.ctrl,
            "shift": self.shift,
            "alt": self.alt,
            "win": self.win,
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> HotkeySpec:
        if not data:
            return cls()
        mode = data.get("mode") or "double"
        if mode not in ("double", "combo"):
            mode = "double"
        return cls(
            scan_code=int(data.get("scan_code") or 41),
            ctrl=bool(data.get("ctrl")),
            shift=bool(data.get("shift")),
            alt=bool(data.get("alt")),
            win=bool(data.get("win")),
            mode=mode,
        )


def _scan_label(scan: int) -> str:
    # common OEM / letter scan codes (set 1)
    known = {
        41: "`/ё",
        16: "Q",
        17: "W",
        18: "E",
        19: "R",
        20: "T",
        21: "Y",
        22: "U",
        23: "I",
        24: "O",
        25: "P",
        30: "A",
        31: "S",
        32: "D",
        33: "F",
        34: "G",
        35: "H",
        36: "J",
        37: "K",
        38: "L",
        44: "Z",
        45: "X",
        46: "C",
        47: "V",
        48: "B",
        49: "N",
        50: "M",
        57: "Space",
        59: "F1",
        60: "F2",
        61: "F3",
        62: "F4",
        63: "F5",
        64: "F6",
        65: "F7",
        66: "F8",
        67: "F9",
        68: "F10",
        87: "F11",
        88: "F12",
        15: "Tab",
        28: "Enter",
        1: "Esc",
        14: "Backspace",
    }
    return known.get(int(scan), f"sc{scan}")


# Exact reserved combos (ctrl, shift, alt, win, key_token)
# key_token: "ANY" matches any key with that mod set (Win alone etc.)
_RESERVED: list[tuple[bool, bool, bool, bool, str]] = [
    # Windows key alone / shell
    (False, False, False, True, "ANY"),
    # Lock / desktop / explorer / settings / run
    (False, False, False, True, "L"),
    (False, False, False, True, "D"),
    (False, False, False, True, "E"),
    (False, False, False, True, "I"),
    (False, False, False, True, "R"),
    (False, False, False, True, "X"),
    (False, False, False, True, "V"),  # clipboard history
    (False, False, False, True, "A"),  # action center / quick settings
    (False, False, False, True, "N"),  # notification center
    (False, False, False, True, "S"),  # search
    (False, False, False, True, "W"),  # widgets
    (False, False, False, True, "Tab"),
    (False, False, False, True, "Space"),  # language/emoji (varies)
    (False, True, False, True, "S"),  # screenshot region Win+Shift+S
    # Task manager / security
    (True, True, False, False, "Esc"),  # Ctrl+Shift+Esc
    (True, False, True, False, "Del"),  # Ctrl+Alt+Del (partial)
    # Alt+Tab / Alt+F4 / Alt+Esc
    (False, False, True, False, "Tab"),
    (False, False, True, False, "F4"),
    (False, False, True, False, "Esc"),
    # Ctrl+Esc = Start
    (True, False, False, False, "Esc"),
    # Copy/paste/cut/undo — never steal
    (True, False, False, False, "C"),
    (True, False, False, False, "V"),
    (True, False, False, False, "X"),
    (True, False, False, False, "Z"),
    (True, False, False, False, "A"),
    (True, False, False, False, "S"),
    (True, False, False, False, "P"),
    (True, False, False, False, "N"),
    (True, False, False, False, "W"),
    (True, False, False, False, "F"),
    (True, False, False, False, "T"),
    # Ctrl+Shift+Esc already; Ctrl+Alt+Arrow (task view snap on some)
    (True, False, True, False, "Arrow"),
]


def check_reserved(spec: HotkeySpec) -> str | None:
    """Return human reason if combo conflicts with Windows / editing, else None."""
    key = _scan_label(spec.scan_code)
    key_u = key.upper() if len(key) == 1 else key
    letter = key_u[0] if len(key_u) == 1 else key_u
    if key.startswith("sc"):
        letter = "OTHER"
    # map known multi-char labels
    if key in ("`/ё",):
        letter = "OEM3"

    # Ctrl+Z/C/V/X even as double-tap — never
    if spec.ctrl and not spec.alt and not spec.win:
        bad = {"Z": "Undo", "C": "Copy", "V": "Paste", "X": "Cut", "A": "Select all"}
        if letter in bad:
            return f"нельзя: Ctrl+{letter} ({bad[letter]})"

    if spec.mode == "double":
        if spec.win and not (spec.ctrl or spec.shift or spec.alt):
            return "Win+… занято системой Windows"
        # bare double-tap without dangerous mod+letter — ok
        if not (spec.ctrl or spec.shift or spec.alt or spec.win):
            return None

    if spec.mode == "combo" and not (spec.ctrl or spec.shift or spec.alt or spec.win):
        return "для одиночного нажатия нужен хотя бы Ctrl / Shift / Alt / Win"

    for c, s, a, w, token in _RESERVED:
        if (c, s, a, w) != (spec.ctrl, spec.shift, spec.alt, spec.win):
            continue
        if token == "ANY":
            return "эта комбинация зарезервирована Windows 11"
        if token.upper() == letter.upper() or token == key or token == key_u:
            return f"занято Windows: {spec.label()}"
        if token == "Arrow" and "arrow" in key.lower():
            return f"занято Windows: {spec.label()}"
    return None


def sanitize_hotkey(spec: HotkeySpec) -> HotkeySpec:
    """If illegal or nonsensical, fall back to Crow Ctrl+Alt+E."""
    # double-tap with modifiers is almost always a mis-capture — normalize to combo
    if spec.mode == "double" and (spec.ctrl or spec.shift or spec.alt or spec.win):
        spec = HotkeySpec(
            scan_code=spec.scan_code,
            ctrl=spec.ctrl,
            shift=spec.shift,
            alt=spec.alt,
            win=spec.win,
            mode="combo",
        )
    if check_reserved(spec) is None:
        return spec
    return HotkeySpec()  # Crow Ctrl+Alt+E
