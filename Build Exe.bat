@echo off
setlocal
rem Builds dist\VampireSurvivorsHelper.exe - a single file your friends can run without Python.
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/
    pause
    exit /b 1
)

echo Installing the packages needed to build - first time only, this can take a minute...
python -m pip install --user --quiet -r requirements.txt -r requirements-build.txt
if errorlevel 1 (
    echo Installing packages failed. See the messages above.
    pause
    exit /b 1
)

echo.
echo Building the exe - this takes one to three minutes...
python -m PyInstaller --noconfirm --clean VampireSurvivorsHelper.spec
if errorlevel 1 (
    echo The build failed. See the messages above.
    pause
    exit /b 1
)

echo.
if exist "dist\VampireSurvivorsHelper.exe" (
    echo Done! Send dist\VampireSurvivorsHelper.exe to your friends - its folder opens now.
    explorer /select,"%~dp0dist\VampireSurvivorsHelper.exe"
) else (
    echo The build finished but the exe was not found in the dist folder.
)
pause
