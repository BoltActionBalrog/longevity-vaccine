@echo off
REM Launch SMACX at 2560x1600 (16:10 - not a native mode on a 16:9 panel, use Windowed), then restore your original resolution on exit.
call "%~dp0game-path.bat"
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-at-resolution.ps1" -Width 2560 -Height 1600 -GameDir "%GAME_DIR%" -GameExe "%GAME_EXE%"
pause
