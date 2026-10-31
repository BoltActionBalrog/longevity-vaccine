@echo off
REM Plain launch of the patched terranx.exe — NO Frida, NO instrumentation.
REM Use this to test the actual patched binary (audio, rendering) without trace artifacts.
call "%~dp0game-path.bat"
cd /d "%GAME_DIR%"
start "" "%GAME_EXE%"
