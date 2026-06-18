@echo off
cd /d "%~dp0"
if not exist venv\Scripts\pythonw.exe (
    echo æ‚É setup.bat ‚ğÀs‚µ‚Ä‚­‚¾‚³‚¢B
    pause
    exit /b 1
)
start "" venv\Scripts\pythonw.exe main.py
