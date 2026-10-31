@echo off
REM Launch SMACX at 1280x1024 (5:4), then restore your original resolution on exit.
call "%~dp0game-path.bat"
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-at-resolution.ps1" -Width 1280 -Height 1024 -GameDir "%GAME_DIR%" -GameExe "%GAME_EXE%"
pause
