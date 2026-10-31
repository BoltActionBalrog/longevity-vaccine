@echo off
REM SMACX UI scaling patcher.
REM Default: dry-run. Pass --apply to commit; --restore to roll back.
setlocal
set "JAVA_HOME=%~dp0..\tools\jdk-21.0.11+10"
set "PATH=%JAVA_HOME%\bin;%PATH%"
"%~dp0..\tools\python\python.exe" "%~dp0scripts\apply_patches.py" %*
endlocal
