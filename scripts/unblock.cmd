@echo off
REM Strip Mark-of-the-Web so SmartScreen stops blocking the launcher.
REM Run once after downloading BonjurLauncher.exe from GitHub.
powershell -NoProfile -Command "Get-ChildItem -LiteralPath '%~dp0' -Filter 'BonjurLauncher*.exe' | Unblock-File"
echo Unblocked. You can run BonjurLauncher.exe now.
pause