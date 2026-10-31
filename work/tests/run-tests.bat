@echo off
REM Layer 1 static patch-integrity suite (no game launch).
REM Runs against the pristine .bak + live patches.yaml.
setlocal
set PY=%~dp0..\..\tools\python\python.exe
"%PY%" -m pytest "%~dp0." %*
endlocal
