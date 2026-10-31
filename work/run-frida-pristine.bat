@echo off
REM Frida-trace the PRISTINE binary (terranx_pristine.exe = copy of the .bak) at a chosen
REM resolution — for capturing UNCONTAMINATED vanilla baselines (no risk of a buggy g<=16
REM gate leaking a patched value into the "native" numbers).
REM
REM Usage:  run-frida-pristine.bat <hook-script.js> <Width> <Height> [pre-script.js]
REM
REM Self-elevates FIRST, then sets SMACX_EXE_NAME in the elevated process (an env var set
REM before elevation would be lost — Start-Process -Verb RunAs starts a fresh environment),
REM then chains to run-frida-at-res.bat, which skips its own elevation when already admin.

if "%~3"=="" (
    echo Usage: run-frida-pristine.bat ^<hook-script.js^> ^<Width^> ^<Height^> [pre.js]
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

set "SMACX_EXE_NAME=terranx_pristine.exe"
echo [PRISTINE trace] SMACX_EXE_NAME=%SMACX_EXE_NAME%
call "%~dp0run-frida-at-res.bat" %*
