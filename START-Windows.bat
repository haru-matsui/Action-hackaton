@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found.
  echo Install Python 3.12+ from https://www.python.org/downloads/
  pause
  exit /b 1
)
python -c "import flask" >nul 2>nul
if errorlevel 1 (
  echo Installing Flask...
  python -m pip install -r backend\requirements.txt
  if errorlevel 1 (
    echo Failed to install dependencies.
    pause
    exit /b 1
  )
)
start "" http://127.0.0.1:5000
python backend\app.py
pause
