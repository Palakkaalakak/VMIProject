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
set DIRTY=
for /f "delims=" %%i in ('git status --porcelain') do set DIRTY=1
if defined DIRTY (
  echo There are local changes in this folder. Putting them aside safely first ^(git stash^); they are put back after the update.
  git stash push --include-untracked -m "before VMI update"
  if errorlevel 1 (
    echo Could not set the local changes aside, so nothing was pulled. The messages above say why.
    pause
    exit /b 1
  )
)
git pull --ff-only origin main
if errorlevel 1 (
  echo The update failed. The messages above say why.
  if defined DIRTY echo Your local changes are safe in the stash: "git stash list" shows them, "git stash pop" puts them back.
  pause
  exit /b 1
)
if defined DIRTY (
  git stash pop
  if errorlevel 1 (
    echo.
    echo The update worked, but your earlier local changes could not be put back automatically.
    echo They are still saved in the stash: "git stash list" shows them. Ask Claude what to keep.
  )
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
