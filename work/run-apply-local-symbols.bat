@echo off
REM Apply our own confirmed symbols (work\symbols\terranx.h) to the terranx project.
REM Default: dry run. Pass --apply to commit.
setlocal
set "JAVA_HOME=%~dp0..\tools\jdk-21.0.11+10"
set "GHIDRA_INSTALL_DIR=%~dp0..\tools\ghidra_12.1_PUBLIC"
set "PATH=%JAVA_HOME%\bin;%PATH%"
"%~dp0..\tools\python\python.exe" "%~dp0scripts\apply_local_symbols.py" %*
endlocal
