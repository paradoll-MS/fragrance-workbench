@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -X utf8 launch.py %*
if errorlevel 1 pause
