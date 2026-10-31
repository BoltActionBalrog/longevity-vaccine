@echo off
REM Run the report_stats.py script against the existing terranx project (no re-analysis).
call "%~dp0..\ghidra-headless.bat" "%~dp0ghidra-projects" terranx -process terranx.exe -noanalysis -scriptPath "%~dp0scripts" -postScript report_stats.py -readOnly
