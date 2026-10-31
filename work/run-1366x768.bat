@echo off
REM Launch SMACX at 1366x768 (16:9, most common 768-height panel), then restore your original resolution on exit.
call "%~dp0game-path.bat"
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-at-resolution.ps1" -Width 1366 -Height 768 -GameDir "%GAME_DIR%" -GameExe "%GAME_EXE%"
pause
