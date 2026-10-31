@echo off
REM Capture numeric modal snapshots at a chosen resolution under Frida
REM (probe_modal.js). Self-elevates (Frida needs SeDebugPrivilege) and restores
REM the original resolution on exit (via run-at-resolution.ps1).
REM
REM Usage:  run-capture.bat <Width> <Height>
REM   e.g.  run-capture.bat 3840 2160     (4K = harmless no-op set/restore)
REM         run-capture.bat 1920 1080
REM
REM At the Frida prompt type  %%resume , then navigate DIRECTLY to each modal you
REM want to baseline; each writes snapshots\<slug>@<WxH>.json automatically. Type
REM 'quit' (or Ctrl+D) when done.

if "%~2"=="" (
    echo Usage: run-capture.bat ^<Width^> ^<Height^>
    exit /b 1
)

REM Detect admin: 'net session' fails non-zero when not elevated.
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Not running as administrator. Requesting UAC elevation...
    echo Look for the User Account Control prompt.
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%~1','%~2' -Verb RunAs"
    exit /b
)

setlocal
call "%~dp0..\game-path.bat"
if not exist "%~dp0snapshots" mkdir "%~dp0snapshots"
echo Spawning %GAME_EXE% under Frida (probe_modal.js) at %~1x%~2 ...
echo At the Frida prompt type   %%resume   then open each modal; type 'quit' when done.
echo.
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\run-at-resolution.ps1" -Width %~1 -Height %~2 -GameDir "%GAME_DIR%" -GameExe "%GAME_EXE%" -FridaDir "%~dp0..\scripts" -FridaHook "..\tests\probe_modal.js"
endlocal
echo.
echo Done. Snapshots are in tests\snapshots\. Press any key to close.
pause >nul
