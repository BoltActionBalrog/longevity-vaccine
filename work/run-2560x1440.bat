@echo off
REM Launch SMACX at 2560x1440 (16:9), then restore your original resolution on exit.
call "%~dp0game-path.bat"
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-at-resolution.ps1" -Width 2560 -Height 1440 -GameDir "%GAME_DIR%" -GameExe "%GAME_EXE%"
pause
