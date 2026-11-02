@echo off
REM Longevity Vaccine - SMACX UI-scaling + cinematics installer (end-user).
REM   run-install.bat               interactive (prompts for AI cinematics)
REM   run-install.bat --ai on       install the HD pack, no prompt
REM   run-install.bat --ai off      keep original .wve (live upscale)
REM   run-install.bat --force       restore + re-patch even if already patched
REM   run-install.bat --no-wait     scripted: print the outcome, do not wait for a key
REM
REM THIS FILE MUST STAY CRLF. cmd's parser desyncs on LF-only batch files, and the multi-line
REM blocks below are exactly what breaks.
setlocal
title Longevity Vaccine Installer - Alpha Centauri UI Scaling + HD Cinematics

set "PY=%~dp0..\tools\python\python.exe"
REM Windows 7 and 8 (kernel 6.1 / 6.2): CPython 3.12 does not start there -- the loader kills it
REM before a line of ours runs -- so the payload carries CPython 3.8 beside it (tools\python38,
REM see scripts\fetch_python38.py). Matched on the bare "6.1."/"6.2." so a localised "Version"
REM word does not matter. bootstrap.py and the DLL's update check make the same choice.
set "PY38="
ver | findstr /R /C:" 6\.[12]\.[0-9]*\]" >nul 2>&1 && set "PY=%~dp0..\tools\python38\python.exe" && set "PY38=1"
REM install.py sits beside this file in a shipped payload (scripts\) and one level down in
REM a checkout (work\scripts\). %PY% needs no such care: "..\tools\python" resolves to the
REM payload root from either.
set "SCRIPT=%~dp0install.py"
if not exist "%SCRIPT%" set "SCRIPT=%~dp0scripts\install.py"

REM --update is the SELF-UPDATE entry point, and it goes through bootstrap.py, not straight
REM to install.py. bootstrap.py owns the generation dance: it verifies the manifest and its
REM kill switches BEFORE anything is touched, and when the installer itself is out of date it
REM downloads the new one and hands over to it rather than patching with a stale patches.yaml.
REM Routing straight to install.py left that whole path unreachable -- the self-update could
REM never run, and a defective bootstrap in the wild is the one thing no later release can fix.
REM install.py stays the worker: bootstrap spawns it for the actual patching.
echo %* | findstr /C:"--update" >nul 2>&1 && call :useboot
goto :afterboot
:useboot
set "SCRIPT=%~dp0bootstrap.py"
if not exist "%SCRIPT%" set "SCRIPT=%~dp0scripts\bootstrap.py"
goto :eof
:afterboot

REM Did the caller ask us not to block? Layer 1 honours --no-wait; so must the pauses here, or an
REM updater-spawned run with an inherited console sits at "Press any key" with nobody there.
set "NOWAIT="
if defined LONGEVITY_NO_WAIT set "NOWAIT=1"
echo %* | findstr /C:"--no-wait" >nul 2>&1 && set "NOWAIT=1"

REM ---------------------------------------------------------------------------
REM EXIT GUARANTEE, layer 2 of 2.
REM
REM install.py's run_guarded() owns every outcome the Python process can reach. This file covers
REM only what Python cannot reach AT ALL: a failure during the module-scope imports, a hard crash
REM before any handler runs, a missing interpreter, or a run under pythonw.exe.
REM
REM Those cannot be detected from the exit code: an uncaught ImportError exits 1, which is
REM indistinguishable from a handled failure, and a Windows fatal status such as 0xC0000005
REM reaches cmd as a NEGATIVE errorlevel. So the handshake is explicit: we create a marker
REM DIRECTORY, run_guarded writes a file inside it, and a missing file afterwards means the guard
REM did not run.
REM
REM The directory is created with `md`, which FAILS if the name already exists -- that is the
REM atomicity we need. %RANDOM% alone is not enough: it is clock-seeded at about one-second
REM granularity, so two installers started within the same second drew the SAME name, and the
REM second one saw the first one's marker and exited silently. The retry counter guarantees a
REM distinct name even when %RANDOM% repeats.
REM ---------------------------------------------------------------------------

set "MBASE=%TEMP%"
if not defined MBASE set "MBASE=%~dp0."
if not exist "%MBASE%\" set "MBASE=%~dp0."

set /a MTRY=0
set "MDIR="
:mkmarker
set /a MTRY+=1
set "MDIR=%MBASE%\longevity-guard-%RANDOM%%RANDOM%-%MTRY%"
md "%MDIR%" 2>nul
if errorlevel 1 (
  if %MTRY% LSS 25 goto :mkmarker
  set "MDIR="
)

if not defined MDIR (
  REM No marker is possible (unwritable TEMP, no writable fallback). We can no longer tell a
  REM silent exit from a reported one, so pause unconditionally at the end instead of guessing.
  set "NOMARKER=1"
) else (
  set "LONGEVITY_GUARD_MARKER=%MDIR%\ok"
)

if not exist "%PY%" goto :incomplete
if not exist "%SCRIPT%" goto :incomplete

REM Windows 7 / 8 only: CPython 3.8's extension loader needs Windows update KB2533623 (2011; part of any
REM Windows 7 that ever took Windows Update). Without it every .pyd import dies before install.py can say
REM a word, so the one import the installer needs first is tried here and the update is named instead.
REM Two probes, no block (`if errorlevel 1` misses a NEGATIVE code; a parenthesised block would expand
REM %ERRORLEVEL% too early). First: does the runtime START at all (a quarantined python38.dll or UCRT
REM forwarder gives a loader status, not 1 -- that is "download again / antivirus", NOT the KB). Then the
REM one import KB2533623 governs.
if not defined PY38 goto :afterkb
"%PY%" -I -c "pass" >nul 2>&1
if not "%ERRORLEVEL%"=="0" goto :nostart
"%PY%" -I -c "import ctypes" >nul 2>&1
if not "%ERRORLEVEL%"=="0" goto :needkb
:afterkb

"%PY%" "%SCRIPT%" %*
set "RC=%ERRORLEVEL%"

if defined NOMARKER goto :unknown_verdict
if not exist "%LONGEVITY_GUARD_MARKER%" goto :no_verdict
rd /s /q "%MDIR%" 2>nul
endlocal & exit /b %RC%

:unknown_verdict
echo.
echo  [installer] Could not create a status marker file, so this window cannot tell
echo  [installer] whether the installer reported its result. Read the text above.
if not defined NOWAIT pause
endlocal & exit /b %RC%

:nostart
set "RC=%ERRORLEVEL%"
if defined MDIR rd /s /q "%MDIR%" 2>nul
echo.
echo  ============================================================
echo     INSTALLATION FAILED
echo  ============================================================
echo  The installer's runtime for this Windows ^(tools\python38\python.exe^) could not start
echo  ^(code %RC%^). A file beside it is missing or blocked -- an antivirus quarantine or an
echo  incomplete extraction is the usual cause.
echo.
echo  Nothing on disk was changed.
echo.
echo  What to do: extract the WHOLE archive again ^(check the antivirus quarantine^), then run
echo  the installer again.
echo.
if not defined NOWAIT pause
REM 11: distinct from 9 ^(package incomplete^) and 10 ^(missing KB2533623^).
endlocal & exit /b 11

:needkb
if defined MDIR rd /s /q "%MDIR%" 2>nul
echo.
echo  ============================================================
echo     INSTALLATION FAILED
echo  ============================================================
echo  This Windows is missing update KB2533623 ^(Windows 7 SP1 / Windows 8^), which the
echo  installer's runtime needs to start.
echo.
echo  Nothing on disk was changed.
echo.
echo  What to do: run Windows Update ^(the update is part of every normal update set^), or
echo  install KB2533623 by hand, then run the installer again.
echo.
if not defined NOWAIT pause
REM 10, not 9: a scripted caller can tell "missing Windows update" from "package incomplete".
endlocal & exit /b 10

:incomplete
if defined MDIR rd /s /q "%MDIR%" 2>nul
echo.
echo  ============================================================
echo     INSTALLATION FAILED
echo  ============================================================
echo  The installer package is incomplete. Expected to find:
echo    "%PY%"
echo    "%SCRIPT%"
echo.
echo  Nothing on disk was changed.
echo.
echo  What to do: download the installer again and extract the WHOLE archive
echo  before running it -- do not run it from inside the zip.
echo.
if not defined NOWAIT pause
endlocal & exit /b 9

:no_verdict
rd /s /q "%MDIR%" 2>nul
echo.
echo  ============================================================
echo     INSTALLER ERROR
echo  ============================================================
echo  The installer stopped before it could report anything ^(exit code %RC%^).
echo  That usually means a missing Python package or a crash in the runtime
echo  itself, not a problem with your game.
echo.
echo  It is not certain how far the install got. Re-running the installer is
echo  safe: it re-checks everything and will finish or repair the install. Your
echo  original exe is backed up as a .bak file beside it.
echo.
echo  What to do: re-run the installer. If it keeps happening, report the exit
echo  code above along with any text shown before this message.
echo.
if not defined NOWAIT pause
endlocal & exit /b %RC%
