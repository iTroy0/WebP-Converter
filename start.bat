@echo off
title WebP Converter
color 0B
chcp 65001 >nul 2>&1

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
echo  ║           WebP  →  Video  Converter  v2.0           ║
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
pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt >nul 2>&1
echo         Done.
echo.
echo  [2/2]  Starting WebP Converter...
echo.
python webp_converter_gui.py
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
pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt >nul 2>&1
pip install pyinstaller >nul 2>&1
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
pyinstaller --noconsole --onefile --clean ^
  --name "WebP Converter" ^
  --hidden-import=moviepy.video.io.ffmpeg_writer ^
  --hidden-import=moviepy.video.compositing.CompositeVideoClip ^
  --hidden-import=imageio_ffmpeg ^
  --collect-data=customtkinter ^
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
exit
