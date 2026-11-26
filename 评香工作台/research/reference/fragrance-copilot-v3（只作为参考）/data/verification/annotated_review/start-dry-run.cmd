@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=C:\Users\26519\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" set "PY=python"

if not defined V3_PORT set "V3_PORT=8768"

cmd /c exit 1
if %errorlevel%==0 (
  echo  服务已在运行，直接打开浏览器。
echo DRY action omitted
echo DRY action omitted
  exit /b
)

echo.
echo  香精项目 Copilot v3
echo  ----------------------------------------
echo  正在启动本地服务...
echo  浏览器将打开 http://127.0.0.1:%V3_PORT%
echo  关闭本窗口即停止。
echo.
echo DRY action omitted
echo DRY action omitted
echo DRY action omitted
echo DRY action omitted


