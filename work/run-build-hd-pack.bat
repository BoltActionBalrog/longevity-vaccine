@echo off
REM Developer-only: AI-upscale the original cinematics (movies\*.wve) into the
REM shippable HD pack (dist\movies-hd\<name>.mp4). NOT run by end users.
REM Needs the drop-in tools in work\video-upscale\tools\ (see work\video-upscale\README.md).
REM   run-build-hd-pack.bat                          all clips
REM   run-build-hd-pack.bat --only opening,gaians    just these
REM   run-build-hd-pack.bat --only gaians --force    re-pick a model for one clip
setlocal
"%~dp0..\tools\python\python.exe" "%~dp0video-upscale\build_hd_pack.py" %*
endlocal
