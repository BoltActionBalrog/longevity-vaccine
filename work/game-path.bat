@echo off
REM Resolves the SMACX install dir into %GAME_DIR% and target exe into %GAME_EXE%.
REM   GAME_DIR: SMACX_GAME_DIR env var > work\game-path.txt > autodetect.
REM   GAME_EXE: SMACX_EXE_NAME  env var > work\game-exe.txt  > terranx.exe.
REM Usage from another batch:   call "%~dp0game-path.bat"   then use %GAME_DIR% / %GAME_EXE%
REM Python counterpart: scripts\config.py
setlocal DisableDelayedExpansion
set "_GD="
set "_GE="

if defined SMACX_GAME_DIR (
    set "_GD=%SMACX_GAME_DIR%"
    goto :dir_done
)
if exist "%~dp0game-path.txt" (
    set /p _GD=<"%~dp0game-path.txt"
    goto :dir_done
)
for %%D in (
    "D:\GOG Galaxy\Games\Sid Meier's Alpha Centauri Planetary Pack"
    "C:\GOG Galaxy\Games\Sid Meier's Alpha Centauri Planetary Pack"
    "C:\GOG Games\Sid Meier's Alpha Centauri Planetary Pack"
    "D:\GOGGalaxy\Games\Alpha Centauri"
) do if not defined _GD if exist "%%~D\terranx.exe" set "_GD=%%~D"
:dir_done

if defined SMACX_EXE_NAME set "_GE=%SMACX_EXE_NAME%"
if not defined _GE if exist "%~dp0game-exe.txt" set /p _GE=<"%~dp0game-exe.txt"
if not defined _GE set "_GE=terranx.exe"

endlocal & set "GAME_DIR=%_GD%" & set "GAME_EXE=%_GE%"
