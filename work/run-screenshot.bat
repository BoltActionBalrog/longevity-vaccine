@echo off
rem Focus-free game screenshot. One-shot by default; --hotkey stays resident
rem and makes PrintScreen capture just the game window (any resolution,
rem Frida attached or not). See work\scripts\screenshot.py --help.
"%~dp0..\tools\python\python.exe" "%~dp0scripts\screenshot.py" %*
