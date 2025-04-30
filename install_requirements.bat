@echo off
title WebP Converter - Install Dependencies
color 0A

echo --------------------------------------------------
echo     Installing required Python packages...
echo --------------------------------------------------

pip install -r requirements.txt

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Failed to install requirements.
    echo Make sure Python and pip are installed and available in PATH.
    pause
    exit /b 1
)

echo.
echo ✅ All dependencies installed successfully!
pause
