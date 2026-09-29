@echo off
setlocal
set "APP_DIR=%~dp0"
set "PYTHON=%APP_DIR%..\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo Python environment missing: "%PYTHON%"
  echo Run setup.bat in the BRL folder, then try again.
  exit /b 1
)
cd /d "%APP_DIR%"
"%PYTHON%" -m mesh_ui.server %*
exit /b %ERRORLEVEL%
