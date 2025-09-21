REM Seelenmaschine Database Maintenance Script
REM Usage:
REM   maintenance.bat          - Full maintenance (default)
REM   maintenance.bat dry      - Dry run mode
REM   maintenance.bat sqlite   - SQLite only
REM   maintenance.bat lancedb  - LanceDB only
REM   maintenance.bat help     - Show help

setlocal enabledelayedexpansion

echo ========================================
echo Seelenmaschine Database Maintenance Tool
echo ========================================
echo.

IF NOT EXIST ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    call .\.venv\Scripts\activate.bat
    echo Installing dependencies...
    pip install -r requirements.txt
) ELSE (
    call .\.venv\Scripts\activate.bat
)

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python not found, please ensure Python is installed and added to PATH
    pause
    exit /b 1
)

REM Check if maintenance script exists
if not exist "database_maintenance.py" (
    echo Error: database_maintenance.py file not found
    pause
    exit /b 1
)

REM Parse command line arguments
set "MODE=--all"
set "EXTRA_ARGS="

if "%1"=="help" (
    python database_maintenance.py --help
    pause
    exit /b 0
)

if "%1"=="dry" (
    set "EXTRA_ARGS=--dry-run"
    echo Mode: Dry run (preview mode)
) else if "%1"=="sqlite" (
    set "MODE=--sqlite"
    echo Mode: SQLite database only
) else if "%1"=="lancedb" (
    set "MODE=--lancedb"
    echo Mode: LanceDB database only
) else (
    echo Mode: Full maintenance (SQLite + LanceDB)
)

echo.
echo Starting database maintenance...
echo.

REM Execute maintenance script
python database_maintenance.py %MODE% %EXTRA_ARGS% --verbose

REM Check execution result
if errorlevel 1 (
    echo.
    echo ========================================
    echo Error occurred during maintenance!
    echo Please check the error messages above
    echo ========================================
) else (
    echo.
    echo ========================================
    echo Database maintenance completed successfully!
    echo ========================================
)

echo.
echo Press any key to exit...
pause >nul
