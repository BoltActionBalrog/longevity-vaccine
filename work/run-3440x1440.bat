@echo off
REM Launch SMACX at 3440x1440 (21:9 ultrawide), then restore your original resolution on exit.
REM Not a native panel mode on a 3840x2160 display - set PRACX to Windowed first.
call "%~dp0game-path.bat"
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-at-resolution.ps1" -Width 3440 -Height 1440 -GameDir "%GAME_DIR%" -GameExe "%GAME_EXE%"
pause
