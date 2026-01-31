@echo off
REM Start Seelenmaschine Telegram Bot for Windows

setlocal

set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%.venv"

REM Check and activate virtual environment if available
if exist "%VENV_DIR%\Scripts\activate.bat" (
    call "%VENV_DIR%\Scripts\activate.bat"
    set "PYTHON_CMD=%VENV_DIR%\Scripts\python.exe"
) else (
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
    echo Usage: start-telegram.bat ^<profile^>
    exit /b 1
)

%PYTHON_CMD% src/main_telegram.py %1
