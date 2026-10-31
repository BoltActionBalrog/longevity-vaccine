@echo off
REM ============================================================================
REM Launch the PRISTINE PRACX base (terranx_PRACX.exe.bak, MD5 2d0b1438) at
REM 1600x1200 (4:3) so we can see how the un-OUR-patched game renders the faction
REM quote-box portrait frame at the resolution where our patched build shows the
REM black right/bottom cutoff. Our patched terranx_PRACX.exe is NEVER touched.
REM
REM It refreshes a playable copy "terranx_pristine.exe" straight from the .bak each
REM run, then hands that exe to run-at-resolution.ps1 (which safely swaps the ini
REM resolution and restores it on exit).
REM
REM Navigate in-game: %resume not needed (no Frida) -> Start Game -> Choose Your
REM Factions -> SELECT a faction so the portrait + quote box show -> screenshot the
REM bottom-left quote box -> quit. Save the shot as refs\pristine\FactionSelect_1600.png.
REM ============================================================================
setlocal
call "%~dp0game-path.bat"
set "SRC=%GAME_DIR%\terranx_PRACX.exe.bak"
set "DST=%GAME_DIR%\terranx_pristine.exe"
if not exist "%SRC%" (
  echo [error] pristine base not found: "%SRC%"
  pause
  exit /b 1
)
echo [info] refreshing pristine copy from .bak ...
copy /Y "%SRC%" "%DST%" >nul
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-at-resolution.ps1" -Width 1600 -Height 1200 -GameDir "%GAME_DIR%" -GameExe "terranx_pristine.exe"
pause
endlocal
