@echo off
setlocal
rem Writes vshelper-diagnose.txt with everything needed to troubleshoot the helper.
cd /d "%~dp0"

echo Vampire Survivors Helper - diagnostic report
echo.
echo 1. Start Vampire Survivors and begin a run.
echo 2. Pick up some weapons and items, then pause the game.
echo 3. Come back here and press any key.
echo.
pause

python --version >nul 2>&1
if errorlevel 1 (
    echo Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo.
echo Collecting information - this can take a minute or two...
python -m vshelper diagnose
echo.
echo Done. Send the file vshelper-diagnose.txt from your Desktop.
pause
