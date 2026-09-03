"""One-time move from the misspelled ~/.bonjur-epta to ~/.bonjour-epta.

The product was always pronounced "Bonjour"; the folder, the launcher and the
repo carried a typo'd "Bonjur" from the first commit. Renaming those is only
safe if the data comes along, so this module runs before anything else reads
config: it copies the old directory to the new name, fixes the autostart entry,
and drops a marker so it never runs twice.

Deliberate choices:

* **Copy, never move.** The old folder stays exactly where it was. If a release
  has to be rolled back, the previous build finds its data untouched. Disk cost
  is a few hundred KB of JSON.
* **No project imports.** Logging itself lives in the config dir, so importing
  logutil here would create the very directory we are about to decide about.
  Failures go to a plain text file next to the new folder.
* **Never fatal.** Every step is guarded. A machine where migration fails keeps
  running on the old folder — degraded, not broken.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

OLD_DIRNAME = ".bonjur-epta"
NEW_DIRNAME = ".bonjour-epta"

OLD_LOG = "bonjur.log"
NEW_LOG = "bonjour.log"

OLD_VBS = "bonjur-autostart.vbs"
OLD_REG_NAME = "BonjurEpta"

MARKER = ".migrated-from-bonjur"

# Files that must never be copied: transient, or regenerated on demand anyway.
_SKIP = {OLD_VBS, "autostart.log"}


def old_dir() -> Path:
    return Path.home() / OLD_DIRNAME


def new_dir() -> Path:
    return Path.home() / NEW_DIRNAME


def _note(text: str) -> None:
    """Breadcrumb for a migration that went sideways. Best effort, never raises."""
    try:
        target = new_dir()
        target.mkdir(parents=True, exist_ok=True)
        with (target / "migration.log").open("a", encoding="utf-8") as fh:
            fh.write(text.rstrip() + "\n")
    except Exception:  # noqa: BLE001
        pass


def already_done() -> bool:
    try:
        return (new_dir() / MARKER).is_file()
    except Exception:  # noqa: BLE001
        return False


def _copy_tree(src: Path, dst: Path) -> tuple[int, int]:
    """Copy src into dst without clobbering anything already there.

    Returns (copied, skipped). Files that already exist in the destination win:
    if the user has run the new build once and changed a setting, the stale
    value from the old folder must not overwrite it.
    """
    copied = skipped = 0
    for root, _dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        out_dir = dst / rel
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            _note(f"mkdir failed {out_dir}: {exc}")
            continue
        for name in files:
            if name in _SKIP:
                skipped += 1
                continue
            # The log gets the new name; everything else keeps its own.
            out_name = NEW_LOG if name == OLD_LOG else name
            target = out_dir / out_name
            if target.exists():
                skipped += 1
                continue
            try:
                shutil.copy2(Path(root) / name, target)
                copied += 1
            except Exception as exc:  # noqa: BLE001
                _note(f"copy failed {name}: {exc}")
                skipped += 1
    return copied, skipped


def _fix_autostart() -> None:
    """Drop the old Run entry and its VBS; the app rewrites its own on next sync.

    Only the stale key is removed here. Re-registering is autostart.sync()'s job
    and it runs a few lines later in main() with the correct new paths — doing
    it twice would just write the same value.
    """
    if sys.platform != "win32":
        return
    try:
        import winreg

        path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, OLD_REG_NAME)
                _note(f"removed stale Run entry {OLD_REG_NAME}")
            except FileNotFoundError:
                pass
    except Exception as exc:  # noqa: BLE001
        _note(f"registry cleanup failed: {exc}")

    try:
        stale = old_dir() / OLD_VBS
        if stale.is_file():
            stale.unlink()
    except Exception as exc:  # noqa: BLE001
        _note(f"vbs cleanup failed: {exc}")


def run() -> bool:
    """Migrate if needed. True when this call did the work.

    Safe to call on every start: the marker short-circuits it, and even without
    the marker the copy skips files that already exist.
    """
    try:
        new = new_dir()
        if already_done():
            return False

        old = old_dir()
        if not old.is_dir():
            # Fresh install — nothing to carry over, just claim the new name so
            # we never look again.
            try:
                new.mkdir(parents=True, exist_ok=True)
                (new / MARKER).write_text("fresh install\n", encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                _note(f"marker write failed: {exc}")
            return False

        new.mkdir(parents=True, exist_ok=True)
        copied, skipped = _copy_tree(old, new)
        _fix_autostart()

        (new / MARKER).write_text(
            f"copied from {old}\nfiles copied: {copied}\nfiles skipped: {skipped}\n"
            "the old folder was left untouched on purpose — delete it by hand\n"
            "once you are happy the new one works\n",
            encoding="utf-8",
        )
        _note(f"migration ok: {copied} copied, {skipped} skipped, source kept at {old}")
        return True
    except Exception as exc:  # noqa: BLE001
        _note(f"migration aborted: {exc}")
        return False