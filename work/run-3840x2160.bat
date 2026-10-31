@echo off
REM Launch SMACX at 3840x2160 (16:9, native), then restore your original resolution on exit.
call "%~dp0game-path.bat"
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-at-resolution.ps1" -Width 3840 -Height 2160 -GameDir "%GAME_DIR%" -GameExe "%GAME_EXE%"
pause
