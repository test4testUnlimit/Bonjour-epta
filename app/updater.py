"""Auto-update from the PUBLIC Bonjur-epta releases feed.

Same shape as OpenWind and MyDash: a `latest.json` asset attached to the newest
non-prerelease, fetched anonymously. No access token ever sits next to a shipped
binary — the code repo here happens to be public too, so it doubles as the feed
and no separate `-releases` repo is needed.

Flow: fetch -> decide -> prompt -> download + verify sha256 -> swap the launcher
exe -> run it. The launcher then sees its version differ from the VERSION file
and does its normal extract-and-relaunch.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from . import logutil

FEED_URL = (
    "https://github.com/test4testUnlimit/Bonjur-epta"
    "/releases/latest/download/latest.json"
)
RELEASES_PAGE = "https://github.com/test4testUnlimit/Bonjur-epta/releases/latest"

# Outcomes. A manifest we cannot parse is "cannot tell", never "up to date":
# silently doing nothing on a broken feed is how an app stops updating forever.
UPDATE_AVAILABLE = "update"
UP_TO_DATE = "current"
DISMISSED = "dismissed"
BAD_MANIFEST = "bad"

_LAUNCHER_NAME = "BonjurLauncher.exe"
_LAUNCHER_GLOB = "BonjurLauncher*.exe"


# ── pure logic (unit-tested) ──────────────────────────────────────────


def parse_version(text: str | None) -> tuple[int, ...] | None:
    """'3.1.2' -> (3, 1, 2). Anything else -> None."""
    if not text:
        return None
    m = re.match(r"^\s*v?(\d+(?:\.\d+){0,3})\s*$", str(text))
    if not m:
        return None
    return tuple(int(p) for p in m.group(1).split("."))


def compare(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    """-1 / 0 / 1. Missing components count as zero, so 3.1 == 3.1.0."""
    width = max(len(a), len(b))
    pa = a + (0,) * (width - len(a))
    pb = b + (0,) * (width - len(b))
    return (pa > pb) - (pa < pb)


def parse_manifest(text: str | None) -> dict | None:
    """Validate the feed payload. Returns None if it is unusable."""
    if not text:
        return None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if parse_version(data.get("version")) is None:
        return None
    url = str(data.get("url") or "")
    if not url.lower().startswith("https://"):
        return None
    return {
        "version": str(data["version"]).strip().lstrip("vV"),
        "url": url,
        "sha256": str(data.get("sha256") or "").strip().lower(),
        "notes": str(data.get("notes") or ""),
        "date": str(data.get("date") or ""),
    }


def decide(local: str, info: dict | None, skipped: str = "") -> str:
    """Four outcomes, and we never act on a bad one."""
    if not info:
        return BAD_MANIFEST
    remote_v = parse_version(info.get("version"))
    local_v = parse_version(local)
    if remote_v is None:
        return BAD_MANIFEST
    # An unreadable local version must not block updating — treat it as ancient.
    if local_v is None:
        local_v = (0,)
    if compare(remote_v, local_v) <= 0:
        return UP_TO_DATE
    if skipped and parse_version(skipped) == remote_v:
        return DISMISSED
    return UPDATE_AVAILABLE


CHECK_INTERVAL_S = 24 * 3600


def due(last_check: float, now: float, interval: float = CHECK_INTERVAL_S) -> bool:
    """Is the daily background check owed?

    A stamp in the future means the clock moved (or the file was hand-edited);
    check now rather than go quiet until the calendar catches up.
    """
    try:
        last = float(last_check or 0.0)
    except (TypeError, ValueError):
        return True
    if last <= 0 or last > now:
        return True
    return (now - last) >= interval


def format_notes(notes: str) -> str:
    """Release notes as a plain bullet list — the feed writes one per line."""
    out = []
    for raw in str(notes or "").replace("\r", "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if not line.startswith(("-", "*", "•")):
            line = "- " + line
        out.append("• " + line.lstrip("-*• ").strip())
    return "\n".join(out)


def asset_name(url: str) -> str:
    """Filename from the download URL, or '' when it is not an exe."""
    name = url.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]
    # Allowlist, not a blocklist: the feed must never get to pick the path we
    # write to, and a plain name is all a release asset ever needs.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.exe", name):
        return ""
    return name


# ── IO ────────────────────────────────────────────────────────────────


def install_dir() -> Path:
    """Folder holding main.py — the launcher lives here too."""
    return Path(__file__).resolve().parent.parent


def launcher_path() -> Path | None:
    """The installed launcher exe, if this is a real install and not a git checkout.

    Releases up to 3.1.4 carried the version in the asset name, so an upgraded
    install can still hold BonjurLauncher_3.1.4.exe next to the current
    BonjurLauncher.exe. The unversioned one wins.
    """
    root = install_dir()
    plain = root / _LAUNCHER_NAME
    if plain.is_file():
        return plain
    try:
        hits = sorted(root.glob(_LAUNCHER_GLOB))
    except OSError:
        return None
    return hits[-1] if hits else None


def fetch_manifest(url: str = FEED_URL, timeout: float = 12.0) -> dict | None:
    """Anonymous GET of latest.json. None on any failure — caller reports BAD_MANIFEST."""
    from . import netcerts

    try:
        with netcerts.client(timeout=timeout, follow_redirects=True) as c:
            r = c.get(url, headers={"Accept": "application/json"})
            if r.status_code != 200:
                logutil.get().info("update feed http %s", r.status_code)
                return None
            return parse_manifest(r.text)
    except Exception:  # noqa: BLE001
        logutil.exc("update feed fetch")
        return None


def download(url: str, dest: Path, sha256: str = "", timeout: float = 120.0) -> bool:
    """Stream to dest and verify. A wrong hash leaves nothing behind."""
    from . import netcerts

    log = logutil.get()
    digest = hashlib.sha256()
    try:
        with netcerts.client(timeout=timeout, follow_redirects=True) as c:
            with c.stream("GET", url) as r:
                if r.status_code != 200:
                    log.warning("update download http %s", r.status_code)
                    return False
                with dest.open("wb") as fh:
                    for chunk in r.iter_bytes(65536):
                        digest.update(chunk)
                        fh.write(chunk)
    except Exception:  # noqa: BLE001
        logutil.exc("update download")
        dest.unlink(missing_ok=True)
        return False

    if dest.stat().st_size < 50_000:
        log.warning("update download too small: %s bytes", dest.stat().st_size)
        dest.unlink(missing_ok=True)
        return False
    # Verify only when the feed carries a hash: an older manifest without one
    # must not turn into an unskippable error.
    if sha256 and digest.hexdigest() != sha256:
        log.warning("update sha256 mismatch: %s != %s", digest.hexdigest(), sha256)
        dest.unlink(missing_ok=True)
        return False
    return True


def unblock_file(path: Path) -> None:
    """Strip the Mark-of-the-Web so SmartScreen does not block the new launcher.

    A file downloaded by the app itself is no more dangerous than the running
    app, yet Windows still flags it as "from the internet". Removing the
    Zone.Identifier stream is the documented unblock; failure is harmless.
    """
    if os.name != "nt":
        return
    try:
        import subprocess

        subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                f"Unblock-File -LiteralPath {str(path)!r}",
            ],
            capture_output=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:  # noqa: BLE001
        logutil.exc("unblock_file")


def apply(info: dict) -> bool:
    """Swap the launcher exe and arm it to start once we are gone.

    Returns False without touching anything if the download or the hash fails,
    so the caller can just tell the user to try later.
    """
    log = logutil.get()
    name = asset_name(info.get("url", ""))
    if not name:
        log.warning("update url is not an exe: %s", info.get("url"))
        return False

    old = launcher_path()
    target_dir = old.parent if old else install_dir()
    new_path = target_dir / name
    part = target_dir / (name + ".part")
    part.unlink(missing_ok=True)

    if not download(info["url"], part, info.get("sha256", "")):
        return False

    try:
        os.replace(part, new_path)
    except OSError:
        logutil.exc("update swap")
        part.unlink(missing_ok=True)
        return False

    unblock_file(new_path)  # keep SmartScreen quiet for the freshly downloaded exe

    # Sweep every other launcher, not just the one we happened to find. Releases
    # up to 3.1.4 were named per version, and a leftover one is a loaded gun:
    # clicking it reinstalls its own embedded payload, i.e. a silent downgrade.
    for stale in target_dir.glob(_LAUNCHER_GLOB):
        if stale.name == new_path.name:
            continue
        try:
            stale.unlink()
        except OSError:
            log.info("could not remove old launcher %s", stale)

    from .restart import schedule_run

    if not schedule_run([str(new_path)], str(target_dir)):
        log.warning("update: launcher downloaded but could not be armed")
        return False
    return True
