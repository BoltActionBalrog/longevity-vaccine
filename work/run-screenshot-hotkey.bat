@echo off
rem Double-clickable: stays resident; the Pause or Home key captures the game window
rem at any resolution without touching its focus (Frida-safe).
rem Start it before or after the game — it finds the window per keypress.
rem Close this window to stop.
rem
rem Self-elevates via UAC: run-frida.bat spawns the game elevated, and UIPI
rem blocks hotkey delivery to a lower-integrity listener while an elevated
rem window has focus — so the listener must be elevated too.

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting UAC elevation ^(hotkeys don't reach a non-elevated
    echo listener while the elevated game/Frida window has focus^)...
    if "%~1"=="" (
        powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    ) else (
        powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
    )
    exit /b
)

title SMAC screenshot hotkey (Pause or Home)
"%~dp0..\tools\python\python.exe" -u "%~dp0scripts\screenshot.py" --hotkey %*
pause
