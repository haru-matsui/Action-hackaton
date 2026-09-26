# PM-Radar — Windows EXE

This project is prepared for a Windows single-file executable build with PyInstaller.

## Build

1. Install Python 3.12+ on Windows.
2. Open this folder.
3. Double-click `BUILD-Windows.bat`.
4. The executable will be created at `dist\PM-Radar.exe`.
5. Copy `PM-Radar.exe` anywhere you want.
6. Double-click `PM-Radar.exe`.

The application opens its web interface at `http://127.0.0.1:5000` automatically.

## User data

The application stores its editable database outside the EXE in:

`%LOCALAPPDATA%\PM-Radar\data\db.json`

This prevents data from being lost when a PyInstaller one-file executable is updated or restarted.

## Important

The EXE must be built on Windows. PyInstaller creates native executables for the operating system on which it runs, so a Windows `.exe` should be produced by running `BUILD-Windows.bat` on Windows.
