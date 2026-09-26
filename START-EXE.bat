@echo off
setlocal
cd /d "%~dp0"
if not exist "dist\PM-Radar.exe" (
    echo PM-Radar.exe was not found.
    echo Run BUILD-Windows.bat first.
    pause
    exit /b 1
)
start "" "dist\PM-Radar.exe"
