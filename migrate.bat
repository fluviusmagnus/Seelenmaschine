@echo off
REM Seelenmaschine Migration Tool Wrapper for Windows
REM Quick wrapper for running the unified migration tool

setlocal

set "SCRIPT_DIR=%~dp0"
set "MIGRATOR=%SCRIPT_DIR%migration\migrator.py"

REM Check if Python is available
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python is not installed or not in PATH
    exit /b 1
)

REM Check if profile argument is provided
if "%1"=="" (
    echo Usage: migrate.bat ^<profile^> [options]
    echo.
    echo Options:
    echo   --auto       Automatically run all needed migrations
    echo   --force      Force re-run migrations
    echo   --no-backup  Skip automatic backup ^(not recommended^)
    echo.
    echo Examples:
    echo   migrate.bat test              # Interactive mode
    echo   migrate.bat test --auto       # Auto-detect and migrate
    echo   migrate.bat test --force      # Force migration
    echo.
    echo For more information, see MIGRATION_GUIDE.md
    exit /b 1
)

REM Run the migrator
echo Running Seelenmaschine Migration Tool...
echo.
python "%MIGRATOR%" %*
