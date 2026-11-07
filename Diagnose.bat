@echo off
setlocal
rem Writes vshelper-diagnose.txt. Start a run in the game first.
cd /d "%~dp0"
python -m vshelper diagnose
pause
