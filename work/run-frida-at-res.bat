@echo off
REM Launch SMACX UNDER FRIDA at a chosen resolution, then restore the original on exit.
REM Combines run-frida.bat (Frida injection, needs UAC) with run-at-resolution.ps1
REM (crash-safe ini set/restore of ScreenWidth/Height + WindowWidth/Height).
REM
REM Usage:  run-frida-at-res.bat <hook-script.js> <Width> <Height> [pre-script.js]
REM   e.g.  run-frida-at-res.bat hook_boxw.js 1920 1080
REM         run-frida-at-res.bat hook_boxw.js 3840 2160   (4K = harmless no-op set/restore)
REM   Optional 4th arg = an extra script loaded BEFORE the hook (e.g. frida_log_append.js to append the log).
REM
REM Self-elevates via UAC (Frida injection needs SeDebugPrivilege). Once elevated, frida.exe -f
REM blocks until you type 'quit', so the ini is restored to its original resolution afterward.

if "%~3"=="" (
    echo Usage: run-frida-at-res.bat ^<hook-script.js^> ^<Width^> ^<Height^>
    echo   e.g. run-frida-at-res.bat hook_boxw.js 1920 1080
    exit /b 1
)

REM Detect admin: 'net session' fails non-zero when not elevated.
net session >nul 2>&1
if %errorlevel% equ 0 goto :elevated
echo Not running as administrator. Requesting UAC elevation...
echo Look for the User Account Control prompt.
REM Build ArgumentList WITHOUT a trailing empty element: Start-Process -ArgumentList
REM rejects an array containing an empty string ("argument is null or empty"), so only
REM append the optional 4th (pre-script) arg when it is actually present.
set "ELEV_ARGS='%~1','%~2','%~3'"
if not "%~4"=="" set "ELEV_ARGS=%ELEV_ARGS%,'%~4'"
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList %ELEV_ARGS% -Verb RunAs"
exit /b
:elevated

setlocal
echo Running as administrator. Spawning %GAME_EXE% under Frida (%~1) at %~2x%~3 ...
echo Once the Frida prompt appears, type:   %%resume
echo then open Customize Game Rules, then type 'quit' or press Ctrl+D.
echo.

call "%~dp0game-path.bat"
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-at-resolution.ps1" -Width %~2 -Height %~3 -GameDir "%GAME_DIR%" -GameExe "%GAME_EXE%" -FridaHook "%~1" -FridaDir "%~dp0scripts" -FridaPre "%~4"

endlocal
echo.
echo Session ended. Press any key to close this window.
pause >nul
