"""Hard restart — kill this process, start a fresh one.

Single-instance mutex is held until process death, so a detached waiter
must outlive us and only then launch the new client.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import logutil


def _prefer_pythonw(exe: str) -> str:
    """GUI relaunch without console flash."""
    try:
        p = Path(exe)
        if p.name.lower() == "python.exe":
            pyw = p.with_name("pythonw.exe")
            if pyw.is_file():
                return str(pyw)
    except Exception:  # noqa: BLE001
        pass
    return exe


def relaunch_argv() -> list[str]:
    """Argv for a fresh client (drops --startup so window shows)."""
    drop = {"--startup"}
    extra = [a for a in sys.argv[1:] if a not in drop]
    if getattr(sys, "frozen", False):
        return [_prefer_pythonw(sys.executable), *extra]
    # Prefer real path of running script (installed copy next to launcher)
    main_py = Path(sys.argv[0]).resolve() if sys.argv else None
    if main_py is None or main_py.suffix.lower() != ".py" or not main_py.is_file():
        main_py = Path(__file__).resolve().parent.parent / "main.py"
    return [_prefer_pythonw(sys.executable), str(main_py), *extra]


def relaunch_cwd() -> str:
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve().parent)
    main = Path(sys.argv[0]).resolve() if sys.argv else None
    if main is not None and main.suffix.lower() == ".py" and main.is_file():
        return str(main.parent)
    return str(Path(__file__).resolve().parent.parent)


def schedule_relaunch() -> bool:
    """Arm a detached process that starts us again after this PID exits."""
    log = logutil.get()
    argv = relaunch_argv()
    cwd = relaunch_cwd()
    pid = os.getpid()
    log.info("schedule relaunch pid=%s argv=%s cwd=%s", pid, argv, cwd)

    if sys.platform == "win32":
        return _schedule_win(pid, argv, cwd)
    return _schedule_posix(pid, argv, cwd)


def _cmd_quote(s: str) -> str:
    """Quote for cmd.exe (double quotes, escape inner ")."""
    return '"' + s.replace('"', '""') + '"'


def _schedule_win(pid: int, argv: list[str], cwd: str) -> bool:
    """
    Write a temp .cmd that waits for PID death, then `start`s the app.
    Launch via ShellExecute so the waiter is outside our process job
    (PowerShell DETACHED often dies with the parent → silent fail).
    """
    log = logutil.get()
    try:
        log_path = Path(tempfile.gettempdir()) / "bonjur-relaunch.log"
        bat_path = Path(tempfile.gettempdir()) / f"bonjur-relaunch-{pid}.cmd"

        exe = argv[0]
        args = argv[1:]
        # start "" /D "cwd" "exe" "arg1" "arg2" ...
        start_line = (
            f'start "bonjour-epta" /D {_cmd_quote(cwd)} '
            + " ".join(_cmd_quote(a) for a in [exe, *args])
        )

        bat = "\r\n".join(
            [
                "@echo off",
                "setlocal",
                f"echo relaunch wait pid={pid} > {_cmd_quote(str(log_path))}",
                f"echo argv={_cmd_quote(' '.join(argv))} >> {_cmd_quote(str(log_path))}",
                f"echo cwd={_cmd_quote(cwd)} >> {_cmd_quote(str(log_path))}",
                ":wait",
                # tasklist filter is exact PID; findstr confirms row exists
                f'tasklist /FI "PID eq {int(pid)}" 2>nul | findstr /I /C:"{int(pid)}" >nul',
                "if not errorlevel 1 (",
                "  timeout /t 1 /nobreak >nul",
                "  goto wait",
                ")",
                f"echo pid gone, starting >> {_cmd_quote(str(log_path))}",
                f"cd /d {_cmd_quote(cwd)}",
                start_line,
                "if errorlevel 1 (",
                f"  echo start failed err=%errorlevel% >> {_cmd_quote(str(log_path))}",
                ") else (",
                f"  echo start ok >> {_cmd_quote(str(log_path))}",
                ")",
                'del "%~f0" >nul 2>&1',
                "",
            ]
        )
        bat_path.write_text(bat, encoding="utf-8")
        log.info("relaunch bat=%s", bat_path)

        # ShellExecute — independent of parent console/job
        try:
            import ctypes

            # SW_HIDE = 0
            rc = int(
                ctypes.windll.shell32.ShellExecuteW(
                    None,
                    "open",
                    str(bat_path),
                    None,
                    cwd,
                    0,
                )
            )
            # >32 means success for ShellExecute
            if rc > 32:
                log.info("ShellExecute relaunch ok rc=%s", rc)
                return True
            log.warning("ShellExecute failed rc=%s, fallback Popen", rc)
        except Exception:  # noqa: BLE001
            logutil.exc("ShellExecute relaunch")

        # Fallback: cmd /c start — still break away from parent
        creation = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creation |= subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            creation |= subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        # CREATE_BREAKAWAY_FROM_JOB if allowed
        creation |= 0x01000000
        subprocess.Popen(
            ["cmd.exe", "/c", str(bat_path)],
            cwd=cwd,
            close_fds=True,
            creationflags=creation,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.info("Popen cmd relaunch armed")
        return True
    except Exception:  # noqa: BLE001
        logutil.exc("schedule relaunch win")
        return False


def _schedule_posix(pid: int, argv: list[str], cwd: str) -> bool:
    try:
        parts = " ".join(_sh_quote(a) for a in argv)
        cmd = (
            f"while kill -0 {int(pid)} 2>/dev/null; do sleep 0.15; done; "
            f"cd {_sh_quote(cwd)} && exec {parts}"
        )
        subprocess.Popen(
            ["bash", "-c", cmd],
            cwd=cwd,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:  # noqa: BLE001
        logutil.exc("schedule relaunch posix")
        return False


def _sh_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"
