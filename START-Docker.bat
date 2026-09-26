@echo off
setlocal
cd /d "%~dp0"
docker compose up -d --build
if errorlevel 1 (
    echo Docker could not start. Check that Docker Desktop is running.
    pause
    exit /b 1
)
start "" "http://127.0.0.1:5000/"
