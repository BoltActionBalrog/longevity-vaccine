@echo off
REM Headless import + auto-analysis of terranx.exe into the project.
call "%~dp0game-path.bat"
REM Ghidra names the program after the imported file; the analysis scripts all
REM expect the program to be named "terranx.exe". Stage the configured target
REM (%GAME_EXE%, e.g. terranx_PRACX.exe) under that name before importing.
set "_STAGE=%TEMP%\smacx_import"
if not exist "%_STAGE%" mkdir "%_STAGE%"
copy /Y "%GAME_DIR%\%GAME_EXE%" "%_STAGE%\terranx.exe" >nul
if not exist "%~dp0ghidra-projects" mkdir "%~dp0ghidra-projects"
call "%~dp0..\ghidra-headless.bat" "%~dp0ghidra-projects" terranx -import "%_STAGE%\terranx.exe" -overwrite
