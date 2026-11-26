@echo off
cd /d "%~dp0"
python -c "import openpyxl" >nul 2>&1
if errorlevel 1 (
    echo Run: python -m pip install -r requirements.txt
    pause
    exit /b 1
)
python launch.py
if errorlevel 1 pause
