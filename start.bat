@echo off
title WebP Converter - Start Menu
color 0B

:menu
cls
echo ============================================
echo         WebP Converter - Main Menu
echo ============================================
echo.
echo [1] Run WebP Converter (install requirements)
echo [2] Build WebP Converter EXE
echo [3] Exit
echo.
set /p choice="Enter your choice (1/2/3): "

if "%choice%"=="1" goto run
if "%choice%"=="2" goto build
if "%choice%"=="3" exit
goto menu

:run
echo.
echo [*] Installing requirements...
pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt >nul 2>&1
echo [*] Running script...
python webp_converter_gui.py
pause
goto menu

:build
echo.
echo [*] Installing requirements...
pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt >nul 2>&1
echo [*] Cleaning previous builds...
rmdir /s /q build >nul 2>&1
rmdir /s /q dist >nul 2>&1
del /f /q *.spec >nul 2>&1
echo [*] Building EXE...
pyinstaller --noconsole --onefile --clean webp_converter_gui.py --hidden-import=moviepy.editor --hidden-import=moviepy.video.io.ffmpeg_writer --hidden-import=moviepy.video.io.VideoFileClip --hidden-import=imageio_ffmpeg
pause
goto menu
