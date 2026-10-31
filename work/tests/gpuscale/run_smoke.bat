@echo off
rem Build + run the gpuscale smoke test (x86, like uimod.dll). Opens a window for under a second.
setlocal
set VS=C:\Program Files\Microsoft Visual Studio\2022\Community
call "%VS%\VC\Auxiliary\Build\vcvarsall.bat" x86 >nul
set OUT=%TEMP%\gpuscale_smoke
if not exist "%OUT%" mkdir "%OUT%"
cl /nologo /EHsc /O2 /std:c++17 /DWIN32_LEAN_AND_MEAN /DNOMINMAX /Fo"%OUT%\\" /Fe"%OUT%\gpuscale_smoke.exe" ^
   "%~dp0gpuscale_smoke.cpp" "%~dp0..\..\..\src\uimod\src\gpuscale.cpp" user32.lib gdi32.lib || exit /b 1
"%OUT%\gpuscale_smoke.exe"
