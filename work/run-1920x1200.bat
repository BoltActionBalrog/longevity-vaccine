@echo off
REM Launch SMACX at 1920x1200 (16:10 - not a native mode on a 16:9 panel, use Windowed), then restore your original resolution on exit.
call "%~dp0game-path.bat"
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-at-resolution.ps1" -Width 1920 -Height 1200 -GameDir "%GAME_DIR%" -GameExe "%GAME_EXE%"
pause
