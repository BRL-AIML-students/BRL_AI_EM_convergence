@echo off
setlocal
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Run setup.ps1 first. 1>&2
  exit /b 1
)
rem Preserve the caller's working directory so relative CAD/NAS paths stay valid.
"%~dp0.venv\Scripts\python.exe" -B -X utf8 "%~dp0convert_cad_to_nastran_surface_mesh.py" %*
exit /b %errorlevel%
