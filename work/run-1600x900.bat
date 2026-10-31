@echo off
REM Launch SMACX at 1600x900 (16:9), then restore your original resolution on exit.
call "%~dp0game-path.bat"
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-at-resolution.ps1" -Width 1600 -Height 900 -GameDir "%GAME_DIR%" -GameExe "%GAME_EXE%"
pause
