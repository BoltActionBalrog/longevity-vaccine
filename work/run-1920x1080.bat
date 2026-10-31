@echo off
REM Launch SMACX at 1920x1080 (16:9), then restore your original resolution on exit.
call "%~dp0game-path.bat"
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-at-resolution.ps1" -Width 1920 -Height 1080 -GameDir "%GAME_DIR%" -GameExe "%GAME_EXE%"
pause
