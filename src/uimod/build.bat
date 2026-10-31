@echo off
REM Command-line build of uimod.dll from the SAME Visual Studio project the IDE uses
REM (uimod.vcxproj), so CLI and IDE builds are identical. Win32/x86 only -- terranx.exe
REM is a 32-bit process. No system PATH dependency; MSBuild is sourced from the VS install.
REM Usage: build.bat [Debug|Release]   (default Release)
setlocal

set "CONFIG=%~1"
if "%CONFIG%"=="" set "CONFIG=Release"

set "VS=C:\Program Files\Microsoft Visual Studio\2022\Community"
set "MSBUILD=%VS%\MSBuild\Current\Bin\MSBuild.exe"
if not exist "%MSBUILD%" ( echo [build] MSBuild not found: "%MSBUILD%" & exit /b 1 )

"%MSBUILD%" "%~dp0uimod.vcxproj" /nologo /v:minimal ^
    /p:Configuration=%CONFIG% /p:Platform=Win32 || exit /b 1

echo.
echo [build] Output: %~dp0build\%CONFIG%\uimod.dll
