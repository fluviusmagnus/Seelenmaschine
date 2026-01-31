@echo off
REM Seelenmaschine Migration Tool Wrapper for Windows
REM Quick wrapper for running the unified migration tool

setlocal

set "SCRIPT_DIR=%~dp0"
set "MIGRATOR=%SCRIPT_DIR%migration\migrate.py"

REM Check if Python is available
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python is not installed or not in PATH
    exit /b 1
)

REM Check if profile argument is provided
if "%1"=="" (
    echo Usage: migrate.bat ^<profile^>
    echo.
    echo Example:
    echo   migrate.bat hy
    echo.
    echo For more information, see migration\README.md
    exit /b 1
)

REM Run the migrator
echo Running Seelenmaschine Migration Tool...
echo.
python "%MIGRATOR%" %*
