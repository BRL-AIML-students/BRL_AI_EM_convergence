@echo off
setlocal
set "APP_DIR=%~dp0"
set "PYTHON=%APP_DIR%..\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo Run setup.bat in the BRL folder first.
  exit /b 1
)
cd /d "%APP_DIR%"
"%PYTHON%" -m geometry_mesh.native_ui %*
exit /b %ERRORLEVEL%
