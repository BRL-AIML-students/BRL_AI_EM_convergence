@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
set "result=%ERRORLEVEL%"
if not "%result%"=="0" echo Setup failed. See the error above.
pause
exit /b %result%
