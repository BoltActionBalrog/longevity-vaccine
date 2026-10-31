@echo off
REM Generic Frida launcher for terranx.exe tracing.
REM Loads frida_common.js (shared helpers) followed by the hook script you name.
REM
REM Usage:  run-frida.bat <hook-script.js>
REM   e.g.  run-frida.bat hook_fieldrect.js
REM         run-frida.bat hook_strokecensus.js  (scripts\PROBES.md lists them; run OBSERVERS only)
REM
REM Self-elevates via UAC because Frida injection needs SeDebugPrivilege.

if "%~1"=="" (
    echo Usage: run-frida.bat ^<hook-script.js^>
    echo   e.g. run-frida.bat hook_fieldrect.js
    exit /b 1
)

REM Detect admin: 'net session' fails non-zero when not elevated.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Not running as administrator. Requesting UAC elevation...
    echo Look for the User Account Control prompt.
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%~1' -Verb RunAs"
    exit /b
)

setlocal
echo Running as administrator. Spawning terranx.exe under Frida with %~1 ...
echo.
echo Once the Frida prompt appears, type:   %%resume
echo to start the game, then navigate to the screen you want to trace.
echo To exit: focus this window (Win+Tab), type 'quit' or press Ctrl+D.
echo.

call "%~dp0game-path.bat"
cd /d "%GAME_DIR%"
REM scaling_laws.js publishes globalThis.SL (shared scaling laws; JS port of scripts/scaling_laws.py,
REM diffed against it by tests/test_scaling_js_parity.py). Loaded for EVERY hook so none re-inlines it.
"%~dp0..\tools\python\Scripts\frida.exe" -f "%GAME_EXE%" -l "%~dp0scripts\frida_common.js" -l "%~dp0scripts\scaling_laws.js" -l "%~dp0scripts\%~1"

endlocal
echo.
echo Frida session ended. Press any key to close this window.
pause >nul
