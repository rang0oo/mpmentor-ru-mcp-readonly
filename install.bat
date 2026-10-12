@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 install.py %*
  exit /b %errorlevel%
)

where python >nul 2>nul
if %errorlevel%==0 (
  python install.py %*
  exit /b %errorlevel%
)

echo Python 3.10 or newer is required. Install it from https://python.org/ 1>&2
exit /b 1
