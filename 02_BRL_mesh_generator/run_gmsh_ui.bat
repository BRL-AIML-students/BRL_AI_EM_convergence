@echo off
setlocal
pushd "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.ps1 first. 1>&2
  popd
  exit /b 1
)
".venv\Scripts\python.exe" -m brl_mesh.native_ui %*
set "brlExit=%errorlevel%"
popd
exit /b %brlExit%
