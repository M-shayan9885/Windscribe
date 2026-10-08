@echo off
setlocal
cd /d "%~dp0"

python -m PyInstaller --noconfirm --clean --onefile --windowed --name WALF --add-data "cities_extended.csv;." --collect-all customtkinter --collect-all darkdetect --collect-all speedtest main.py
if errorlevel 1 (
    echo.
    echo Build failed. Install build dependencies with:
    echo   python -m pip install -r requirements-build.txt
    exit /b 1
)

echo.
echo Build complete: "%~dp0dist\WALF.exe"
