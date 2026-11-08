@echo off
setlocal
rem Starts the helper window (which starts Vampire Survivors too, unless switched off in Settings).
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo Python was not found.
    echo Install Python 3.10 or newer from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during setup, then try again.
    pause
    exit /b 1
)

rem UnityPy is only needed for item pictures; install it once if missing.
python -c "import UnityPy" >nul 2>&1
if errorlevel 1 (
    echo Installing UnityPy for item pictures - one time only...
    python -m pip install --user -r requirements.txt
    if errorlevel 1 (
        echo Could not install UnityPy. The helper will still work, just without pictures.
        pause
    )
)

rem The helper starts Vampire Survivors itself (Settings > Game > Start Vampire Survivors...).

rem pythonw runs the helper without a console window.
start "" pythonw -m vshelper
