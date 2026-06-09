@echo off
setlocal EnableExtensions
title WebP Converter
color 0B
chcp 65001 >nul 2>&1

set "PIPLOG=%TEMP%\webp_converter_pip.log"

:: ── Locate Python ─────────────────────────
set "PY="
py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python -c "import sys" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo.
    echo  [ERROR] Python 3 not found on PATH.
    echo          Install it from https://www.python.org/downloads/
    echo          and tick "Add python.exe to PATH" during setup.
    echo.
    pause
    exit /b 1
)

:menu
cls
echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║                                                      ║
echo  ║        ░██╗░░░░░░░██╗███████╗██████╗░██████╗░        ║
echo  ║        ░██║░░██╗░░██║██╔════╝██╔══██╗██╔══██╗        ║
echo  ║        ░╚██╗████╗██╔╝█████╗░░██████╦╝██████╔╝        ║
echo  ║        ░░████╔═████║░██╔══╝░░██╔══██╗██╔═══╝░        ║
echo  ║        ░░╚██╔╝░╚██╔╝░███████╗██████╦╝██║░░░░░        ║
echo  ║        ░░░╚═╝░░░╚═╝░░╚══════╝╚═════╝░╚═╝░░░░░        ║
echo  ║                                                      ║
echo  ║           WebP  →  Video  Converter  v2.2           ║
echo  ║                                                      ║
echo  ╠══════════════════════════════════════════════════════╣
echo  ║                                                      ║
echo  ║   [1]  ▶  Run Application                           ║
echo  ║   [2]  ⚙  Build Standalone EXE                      ║
echo  ║   [3]  ✕  Exit                                       ║
echo  ║                                                      ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
set /p choice="   Enter choice (1/2/3): "

if "%choice%"=="1" goto run
if "%choice%"=="2" goto build
if "%choice%"=="3" goto exit
goto menu

:: ─────────────────────────────────────────
:run
cls
echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║   ▶  LAUNCHING APPLICATION                          ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
echo  [1/2]  Syncing dependencies...
%PY% -m pip install -r requirements.txt >"%PIPLOG%" 2>&1
if errorlevel 1 (
    echo         [ERROR] Dependency install failed:
    echo  ─────────────────────────────────────────────────────
    type "%PIPLOG%"
    echo  ─────────────────────────────────────────────────────
    pause
    goto menu
)
echo         Done.
echo.
echo  [2/2]  Starting WebP Converter...
echo.
%PY% webp_converter_gui.py
if errorlevel 1 (
    echo.
    echo  [WARN] Application exited with an error (code %ERRORLEVEL%^).
)
echo.
echo  ─────────────────────────────────────────────────────
echo   Application closed. Press any key to return to menu.
echo  ─────────────────────────────────────────────────────
pause >nul
goto menu

:: ─────────────────────────────────────────
:build
cls
echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║   ⚙  BUILDING STANDALONE EXE                        ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
echo  [1/4]  Syncing dependencies...
%PY% -m pip install -r requirements.txt >"%PIPLOG%" 2>&1
if errorlevel 1 (
    echo         [ERROR] Dependency install failed:
    type "%PIPLOG%"
    pause
    goto menu
)
%PY% -m pip install pyinstaller >>"%PIPLOG%" 2>&1
if errorlevel 1 (
    echo         [ERROR] PyInstaller install failed:
    type "%PIPLOG%"
    pause
    goto menu
)
echo         Done.
echo.
echo  [2/4]  Removing previous build artifacts...
rmdir /s /q build >nul 2>&1
rmdir /s /q dist  >nul 2>&1
del   /f /q *.spec >nul 2>&1
echo         Done.
echo.
echo  [3/4]  Compiling — this may take a minute...
echo.
%PY% -m PyInstaller --noconsole --onefile --clean ^
  --name "WebP Converter" ^
  --icon=app_icon.ico ^
  --add-data "app_icon.ico;." ^
  --hidden-import=imageio_ffmpeg ^
  --collect-data=customtkinter ^
  --collect-data=imageio_ffmpeg ^
  --collect-data=tkinterdnd2 ^
  --collect-binaries=tkinterdnd2 ^
  webp_converter_gui.py
echo.
echo  [4/4]  Cleaning up build files...
rmdir /s /q build >nul 2>&1
del   /f /q *.spec >nul 2>&1
echo         Done.
echo.
if exist "dist\WebP Converter.exe" (
    echo  ╔══════════════════════════════════════════════════════╗
    echo  ║   ✔  BUILD SUCCESSFUL                               ║
    echo  ║      dist\WebP Converter.exe is ready               ║
    echo  ╚══════════════════════════════════════════════════════╝
) else (
    echo  ╔══════════════════════════════════════════════════════╗
    echo  ║   ✖  BUILD FAILED — check output above              ║
    echo  ╚══════════════════════════════════════════════════════╝
)
echo.
echo  ─────────────────────────────────────────────────────
echo   Press any key to return to menu.
echo  ─────────────────────────────────────────────────────
pause >nul
goto menu

:: ─────────────────────────────────────────
:exit
cls
echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║   Goodbye!                                          ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
timeout /t 1 >nul
exit /b 0
