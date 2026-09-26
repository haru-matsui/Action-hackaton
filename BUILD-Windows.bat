@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo PM-Radar Windows EXE build
echo ========================================
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo Python launcher was not found.
    echo Install Python 3.12+ from https://www.python.org/downloads/
    pause
    exit /b 1
)

py -3 -m pip install --upgrade pip
if errorlevel 1 goto :fail

py -3 -m pip install -r backend\requirements.txt pyinstaller
if errorlevel 1 goto :fail

echo.
echo Building PM-Radar.exe...
py -3 -m PyInstaller --clean --noconfirm PM-Radar.spec
if errorlevel 1 goto :fail

echo.
echo ========================================
echo Build complete.
echo EXE: dist\PM-Radar.exe
echo ========================================
pause
exit /b 0

:fail
echo.
echo BUILD FAILED.
pause
exit /b 1
