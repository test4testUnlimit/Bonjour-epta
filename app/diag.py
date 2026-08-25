"""Session diagnostics — heartbeat (sleep/wake gaps) + foreground snapshot.

After sleep the mouse/keyboard hooks sometimes go quiet until the first
real keypress; the chip then "never appears". Heartbeat gaps > ~90s mark
SLEEP_WAKE in the log so a later BUGMARK can be correlated.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from . import logutil, peers

_HEARTBEAT_S = 30.0
_SLEEP_GAP_S = 90.0

_lock = threading.Lock()
_started_at = 0.0
_last_beat = 0.0
_wake_events: list[tuple[float, float]] = []  # (wall_ts, gap_s)
_thread: threading.Thread | None = None
_stop = threading.Event()


@dataclass(frozen=True)
class FgInfo:
    hwnd: int
    pid: int
    title: str
    exe: str
    layout: str


def start() -> None:
    """Idempotent daemon heartbeat."""
    global _thread, _started_at, _last_beat
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        now = time.perf_counter()
        _started_at = now
        _last_beat = now
        _stop.clear()
        _thread = threading.Thread(target=_loop, daemon=True, name="bonjur-diag")
        _thread.start()
    logutil.get().info(
        "diag heartbeat on every %.0fs (sleep gap ≥%.0fs)",
        _HEARTBEAT_S,
        _SLEEP_GAP_S,
    )


def stop() -> None:
    _stop.set()


def uptime_s() -> float:
    with _lock:
        if not _started_at:
            return 0.0
        return time.perf_counter() - _started_at


def recent_wakes(within_s: float = 3600.0) -> list[tuple[float, float]]:
    """(unix_ts, gap_s) for wakes inside the window."""
    cut = time.time() - within_s
    with _lock:
        return [(ts, gap) for ts, gap in _wake_events if ts >= cut]


def foreground() -> FgInfo | None:
    if __import__("sys").platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = int(user32.GetForegroundWindow() or 0)
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        title = (buf.value or "")[:120]
        exe = _exe_for_pid(int(pid.value)) if pid.value else ""
        tid = user32.GetWindowThreadProcessId(hwnd, None)
        hkl = int(user32.GetKeyboardLayout(tid) & 0xFFFF)
        layout = f"0x{hkl:04X}"
        return FgInfo(hwnd=hwnd, pid=int(pid.value), title=title, exe=exe, layout=layout)
    except Exception:  # noqa: BLE001
        logutil.exc("diag.foreground")
        return None


def snapshot_lines(tag: str = "SNAP") -> list[str]:
    """Structured lines for BUGMARK / log — agent-greppable."""
    lines: list[str] = []
    up = uptime_s()
    lines.append(f"{tag} uptime_s={up:.0f}")
    wakes = recent_wakes()
    if wakes:
        last_ts, last_gap = wakes[-1]
        lines.append(
            f"{tag} last_wake ago_s={time.time() - last_ts:.0f} gap_s={last_gap:.0f} "
            f"wakes_1h={len(wakes)}"
        )
    else:
        lines.append(f"{tag} last_wake=none")
    try:
        from . import copy_guard, input_arbiter

        lines.append(
            f"{tag} copy_guard recent={copy_guard.recent()} "
            f"input_busy={input_arbiter.busy()}"
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import settings as cfg

        s = cfg.get()
        lines.append(
            f"{tag} chivoblya={s.chivoblya_enabled} hotkey={s.hotkey_spec().label()}"
        )
    except Exception:  # noqa: BLE001
        pass
    fg = foreground()
    if fg:
        lines.append(
            f"{tag} fg pid={fg.pid} exe={fg.exe!r} layout={fg.layout} "
            f"title={fg.title!r}"
        )
    else:
        lines.append(f"{tag} fg=none")
    try:
        import ctypes

        seq = int(ctypes.windll.user32.GetClipboardSequenceNumber())
        lines.append(f"{tag} clip_seq={seq}")
    except Exception:  # noqa: BLE001
        pass
    p = peers.list_peers()
    lines.append(f"{tag} peers={peers.summary(p)}")
    return lines


def log_snapshot(tag: str = "SNAP") -> None:
    log = logutil.get()
    for line in snapshot_lines(tag):
        log.info("%s", line)


def _loop() -> None:
    global _last_beat
    log = logutil.get()
    while not _stop.wait(_HEARTBEAT_S):
        now = time.perf_counter()
        with _lock:
            gap = now - _last_beat if _last_beat else 0.0
            _last_beat = now
            up = now - _started_at if _started_at else 0.0
        if gap >= _SLEEP_GAP_S:
            wall = time.time()
            with _lock:
                _wake_events.append((wall, gap))
                if len(_wake_events) > 40:
                    del _wake_events[:-40]
            log.warning(
                "SLEEP_WAKE gap_s=%.0f uptime_s=%.0f — hooks may be stale until real input",
                gap,
                up,
            )
            try:
                peers.log_snapshot("peers after wake")
            except Exception:  # noqa: BLE001
                pass
            log_snapshot("SNAP_WAKE")
        else:
            log.debug("HEARTBEAT uptime_s=%.0f gap_s=%.1f", up, gap)


def _exe_for_pid(pid: int) -> str:
    if not pid:
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(520)
            size = wintypes.DWORD(520)
            # QueryFullProcessImageNameW
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                path = buf.value or ""
                return path.rsplit("\\", 1)[-1] if path else ""
        finally:
            kernel32.CloseHandle(h)
    except Exception:  # noqa: BLE001
        pass
    return ""
