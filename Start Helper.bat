@echo off
setlocal
rem Starts Vampire Survivors (through Steam, if it isn't already running) and the helper window.
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo Python was not found.
    echo Install Python 3.10 or newer from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during setup, then try again.
    pause
    exit /b 1
)

tasklist /FI "IMAGENAME eq VampireSurvivors.exe" 2>nul | find /I "VampireSurvivors.exe" >nul
if errorlevel 1 (
    echo Starting Vampire Survivors through Steam...
    start "" "steam://rungameid/1794680"
)

rem pythonw runs the helper without a console window.
start "" pythonw -m vshelper
