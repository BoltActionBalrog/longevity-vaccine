@echo off
REM Launches Ghidra's analyzeHeadless using the self-contained JDK in tools\.
REM Forwards all arguments to analyzeHeadless.bat.

setlocal
set "JAVA_HOME=%~dp0tools\jdk-21.0.11+10"
set "PATH=%JAVA_HOME%\bin;%PATH%"
call "%~dp0tools\ghidra_12.1_PUBLIC\support\analyzeHeadless.bat" %*
endlocal
