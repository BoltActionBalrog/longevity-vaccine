@echo off
setlocal
"%~dp0..\tools\python\python.exe" "%~dp0scripts\assemble_thunks.py" %*
endlocal
