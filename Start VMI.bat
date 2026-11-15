@echo off
rem One-click start of the VMI Toolkit. Double-click this file. Close the window to stop the app.
title VMI Toolkit
cd /d "%~dp0"

rem 1. find Python 3.11+ (the py launcher first, then python)
set "PY="
where py >NUL 2>NUL && set "PY=py -3"
if not defined PY (where python >NUL 2>NUL && set "PY=python")
if not defined PY (
  echo Python was not found. Install Python 3.11 or newer from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" in the installer, then double-click this file again.
  pause
  exit /b 1
)

rem 2. private environment, created once
if not exist ".venv\Scripts\python.exe" (
  echo Creating the private Python environment, one time only...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo Could not create the environment. Python 3.11 or newer is required.
    pause
    exit /b 1
  )
)

rem 3. install what is missing, start the app, open the browser
".venv\Scripts\python.exe" -m vmi.launch
if errorlevel 1 (
  echo.
  echo The app stopped with an error. The messages above say why.
  pause
)
