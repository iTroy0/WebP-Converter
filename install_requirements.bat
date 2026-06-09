@echo off
setlocal EnableExtensions
title WebP Converter - Install Dependencies
color 0A

echo --------------------------------------------------
echo     Installing required Python packages...
echo --------------------------------------------------

set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python -c "import sys" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo.
    echo [ERROR] Python 3 not found on PATH.
    echo Install it from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during setup.
    pause
    exit /b 1
)

%PY% -m pip install -r requirements.txt

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Failed to install requirements.
    pause
    exit /b 1
)

echo.
echo All dependencies installed successfully!
pause
