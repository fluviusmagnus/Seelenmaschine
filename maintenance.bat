@echo off
REM Seelenmaschine Database Maintenance Script
REM Usage:
REM   maintenance.bat ^<profile^> [options]
REM   Options: --all, --sqlite, --lancedb, --dry-run, --verbose
REM   maintenance.bat help - Show help

setlocal enabledelayedexpansion

echo ========================================
echo Seelenmaschine Database Maintenance Tool
echo ========================================
echo.

REM Check for help
if "%1"=="help" (
    echo Usage:
    echo   maintenance.bat ^<profile^> [options]
    echo.
    echo Required parameter:
    echo   ^<profile^>              Config profile name (e.g., dev, production^)
    echo.
    echo Optional parameters:
    echo   --all                  Maintain all databases (default^)
    echo   --sqlite               Maintain SQLite database only
    echo   --lancedb              Maintain LanceDB database only
    echo   --dry-run              Dry run mode (preview without execution^)
    echo   --verbose, -v          Verbose output mode
    echo.
    echo Examples:
    echo   maintenance.bat dev
    echo   maintenance.bat dev --all
    echo   maintenance.bat dev --sqlite --dry-run
    echo   maintenance.bat dev --lancedb --verbose
    echo   maintenance.bat production --all --dry-run --verbose
    pause
    exit /b 0
)
if "%1"=="--help" goto :show_help
if "%1"=="-h" goto :show_help
goto :continue_help

:show_help
echo Usage:
echo   maintenance.bat ^<profile^> [options]
echo.
echo Required parameter:
echo   ^<profile^>              Config profile name (e.g., dev, production^)
echo.
echo Optional parameters:
echo   --all                  Maintain all databases (default^)
echo   --sqlite               Maintain SQLite database only
echo   --lancedb              Maintain LanceDB database only
echo   --dry-run              Dry run mode (preview without execution^)
echo   --verbose, -v          Verbose output mode
echo.
echo Examples:
echo   maintenance.bat dev
echo   maintenance.bat dev --all
echo   maintenance.bat dev --sqlite --dry-run
echo   maintenance.bat dev --lancedb --verbose
echo   maintenance.bat production --all --dry-run --verbose
pause
exit /b 0

:continue_help

REM Check if profile parameter is provided
if "%1"=="" (
    echo Error: Please provide profile parameter
    echo Usage: maintenance.bat ^<profile^> [options]
    echo Example: maintenance.bat dev --sqlite --dry-run
    echo Use 'maintenance.bat help' for detailed help
    pause
    exit /b 1
)

set "PROFILE=%1"
shift

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
set "PYTHON_ARGS="
set "HAS_MODE=false"

:parse_loop
if "%1"=="" goto :end_parse

if "%1"=="--all" (
    set "PYTHON_ARGS=%PYTHON_ARGS% %1"
    set "HAS_MODE=true"
    shift
    goto :parse_loop
)
if "%1"=="--sqlite" (
    set "PYTHON_ARGS=%PYTHON_ARGS% %1"
    set "HAS_MODE=true"
    shift
    goto :parse_loop
)
if "%1"=="--lancedb" (
    set "PYTHON_ARGS=%PYTHON_ARGS% %1"
    set "HAS_MODE=true"
    shift
    goto :parse_loop
)
if "%1"=="--dry-run" (
    set "PYTHON_ARGS=%PYTHON_ARGS% %1"
    shift
    goto :parse_loop
)
if "%1"=="-v" (
    set "PYTHON_ARGS=%PYTHON_ARGS% %1"
    shift
    goto :parse_loop
)
if "%1"=="--verbose" (
    set "PYTHON_ARGS=%PYTHON_ARGS% %1"
    shift
    goto :parse_loop
)

REM Unknown parameter
echo Unknown parameter: %1
echo Use 'maintenance.bat help' for help
pause
exit /b 1

:end_parse

REM If no mode specified, default to --all
if "%HAS_MODE%"=="false" (
    set "PYTHON_ARGS=--all%PYTHON_ARGS%"
)

echo Profile: %PROFILE%
echo Arguments:%PYTHON_ARGS%
echo.
echo Starting database maintenance...
echo.

REM Execute maintenance script
python database_maintenance.py %PROFILE%%PYTHON_ARGS%

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
