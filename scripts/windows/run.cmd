@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0..\.."
if not exist "backend\.venv\Scripts\python.exe" (
  echo The project Python environment is missing. See docs/Windows运行说明.md.
  pause
  exit /b 1
)
set "LEARNLOOP_ACTION=%~1"
if "%LEARNLOOP_ACTION%"=="" set "LEARNLOOP_ACTION=menu"
"backend\.venv\Scripts\python.exe" -X utf8 "scripts\mac\native.py" %LEARNLOOP_ACTION%
if errorlevel 1 (
  echo Operation failed. Keep this window for troubleshooting.
  pause
  exit /b 1
)
endlocal
