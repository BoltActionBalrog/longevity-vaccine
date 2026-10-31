@echo off
REM Driver for build_ffmpeg_slim.sh: loads the x86 MSVC toolchain (vcvars32) and runs the
REM build script under the bundled MSYS2 bash with the MSVC PATH inherited.
setlocal
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars32.bat" || exit /b 1
set MSYS2_PATH_TYPE=inherit
set CHERE_INVOKING=1
"D:\SmacxUi\tools\msys64\usr\bin\bash.exe" -lc "/d/SmacxUi/tools/build_ffmpeg_slim.sh"
endlocal
