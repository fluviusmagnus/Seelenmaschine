@echo off
REM Seelenmaschine Migration Tool Wrapper for Windows
REM Quick wrapper for running the unified migration tool

setlocal

set "SCRIPT_DIR=%~dp0"
set "MIGRATOR=%SCRIPT_DIR%migration\migrate.py"
set "VENV_DIR=%SCRIPT_DIR%.venv"

REM Check and activate virtual environment if available
if exist "%VENV_DIR%\Scripts\activate.bat" (
    call "%VENV_DIR%\Scripts\activate.bat"
    set "PYTHON_CMD=%VENV_DIR%\Scripts\python.exe"
) else (
    REM Fallback to system Python
    where python >nul 2>&1
    if %errorlevel% neq 0 (
        echo Error: Python is not installed or not in PATH
        exit /b 1
    )
    set "PYTHON_CMD=python"
)

REM Check requirements
set "REQUIREMENTS_FILE=%SCRIPT_DIR%requirements.txt"
if exist "%REQUIREMENTS_FILE%" (
    echo Checking dependencies...
    %PYTHON_CMD% -c "import openai" >nul 2>&1
    if %errorlevel% neq 0 (
        echo Dependencies not installed. Installing from requirements.txt...
        %PYTHON_CMD% -m pip install -r "%REQUIREMENTS_FILE%"
        if %errorlevel% neq 0 (
            echo Error: Failed to install dependencies
            exit /b 1
        )
    )
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
%PYTHON_CMD% "%MIGRATOR%" %*
