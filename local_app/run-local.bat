@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python Launcher was not found. Install Python 3.11 or newer with the py launcher.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating an isolated Python 3 environment...
  py -3 -m venv .venv
  if errorlevel 1 goto :failed
)

if not exist ".venv\.lyre-deps-ready" (
  echo Installing MIDI and local web dependencies. This is needed only once...
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 goto :failed
  type nul > ".venv\.lyre-deps-ready"
)

echo Starting Lyre Bridge at http://127.0.0.1:17321 ...
".venv\Scripts\python.exe" lyre_bridge_server.py %*
if errorlevel 1 goto :failed
exit /b 0

:failed
echo.
echo Startup failed. Keep this window open so the error can be inspected.
pause
exit /b 1
