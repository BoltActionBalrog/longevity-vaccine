@echo off
REM Probe the two title-box 9-slice draws (params, sprite dims, rects, stroke colors).
REM %resume, open Customize Game Rules, quit. Log: work\frida_box_thickness.log
call "%~dp0run-frida.bat" hook_box_thickness.js
