@echo off
REM Build relocation signatures from the 2d0b14 baseline (self-validates),
REM or pass --locate <path-to-new-terranx.exe> to find sites in a new build.
setlocal
"%~dp0..\tools\python\python.exe" "%~dp0scripts\build_signatures.py" %*
endlocal
