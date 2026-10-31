@echo off
REM Trace SMAC UI asset strings to their containing functions, then decompile.
setlocal
set "JAVA_HOME=%~dp0..\tools\jdk-21.0.11+10"
set "GHIDRA_INSTALL_DIR=%~dp0..\tools\ghidra_12.1_PUBLIC"
set "PATH=%JAVA_HOME%\bin;%PATH%"
"%~dp0..\tools\python\python.exe" "%~dp0scripts\trace_assets.py" %*
endlocal
