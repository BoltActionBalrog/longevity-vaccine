@echo off
REM Frida-trace the TRUE VANILLA binary (terranx.exe = un-PRACX'd cc659f + win11 fix) at a
REM chosen resolution — for baselines PRACX cannot provide (e.g. the engine map-zoom pair
REM 0x691E6C/70, which PRACX leaves at -1 because it replaces the zoom machinery).
REM
REM Usage:  run-frida-truevanilla.bat <hook-script.js> <Width> <Height> [pre-script.js]
REM
REM Self-elevates FIRST, then sets SMACX_EXE_NAME in the elevated process, then chains to
REM run-frida-at-res.bat (skips its own elevation when already admin).

if "%~3"=="" (
    echo Usage: run-frida-truevanilla.bat ^<hook-script.js^> ^<Width^> ^<Height^> [pre.js]
    exit /b 1
)

net session >nul 2>&1
if %errorlevel% equ 0 goto :elevated
echo Not running as administrator. Requesting UAC elevation...
set "ELEV_ARGS='%~1','%~2','%~3'"
if not "%~4"=="" set "ELEV_ARGS=%ELEV_ARGS%,'%~4'"
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList %ELEV_ARGS% -Verb RunAs"
exit /b
:elevated

set "SMACX_EXE_NAME=terranx.exe"
echo [TRUE-VANILLA trace] SMACX_EXE_NAME=%SMACX_EXE_NAME%
call "%~dp0run-frida-at-res.bat" %*
