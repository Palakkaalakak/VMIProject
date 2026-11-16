@echo off
rem Pulls the latest code from GitHub and updates the packages. Double-click, then start the app with Start VMI.bat.
title Update VMI Toolkit
cd /d "%~dp0"
where git >NUL 2>nul
if errorlevel 1 (
  echo Git was not found. Install it from https://git-scm.com/downloads then run this again.
  pause
  exit /b 1
)
git diff --quiet --exit-code
if errorlevel 1 (
  echo There are local changes in this folder, so nothing was pulled. Commit or discard them first.
  pause
  exit /b 1
)
git pull --ff-only origin main
if errorlevel 1 (
  echo The update failed. The messages above say why.
  pause
  exit /b 1
)
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "from vmi.launch import ensure_deps; raise SystemExit(0 if ensure_deps() else 1)"
)
echo.
echo The code is now at:
git log -1 --format="  %%h  %%cs  %%s"
echo.
echo Updated. IMPORTANT: close the VMI window if it is still open, then double-click "Start VMI.bat" again
echo (a running app keeps the old code until it is restarted).
pause
