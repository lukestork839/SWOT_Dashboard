@echo off
echo === SWOT Dashboard Setup ===
echo.

REM Check if Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not on your PATH.
    echo.
    echo Please install Python from https://www.python.org/downloads/
    echo IMPORTANT: Check "Add python.exe to PATH" during installation.
    echo.
    echo If Python is already installed, try:
    echo   1. Search "Manage app execution aliases" in the Start Menu
    echo   2. Turn OFF python.exe and python3.exe
    echo   3. Restart this script
    pause
    exit /b 1
)

echo Found Python:
python --version
echo.

REM Create virtual environment if it doesn't exist
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    echo.
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies (this may take a few minutes)...
python -m pip install -r requirements.txt
echo.

REM Launch the dashboard
echo.
echo === Setup complete! Launching dashboard... ===
echo.
echo The dashboard will open at http://localhost:8501
echo Press Ctrl+C in this window to stop it.
echo.
streamlit run dashboard_swot.py
