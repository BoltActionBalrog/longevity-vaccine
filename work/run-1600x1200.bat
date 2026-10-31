@echo off
REM Launch SMACX at 1600x1200 (4:3), then restore your original resolution on exit.
call "%~dp0game-path.bat"
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-at-resolution.ps1" -Width 1600 -Height 1200 -GameDir "%GAME_DIR%" -GameExe "%GAME_EXE%"
pause
