@echo off
REM Launch SMACX at 1024x768 (4:3, native g16 no-op baseline), then restore your original resolution on exit.
call "%~dp0game-path.bat"
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-at-resolution.ps1" -Width 1024 -Height 768 -GameDir "%GAME_DIR%" -GameExe "%GAME_EXE%"
pause
