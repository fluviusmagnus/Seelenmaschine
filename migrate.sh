#!/bin/bash
# Seelenmaschine Migration Tool Wrapper
# Quick wrapper for running the unified migration tool

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
MIGRATOR="$SCRIPT_DIR/migration/migrate.py"
VENV_DIR="$SCRIPT_DIR/.venv"

# Check and activate virtual environment if available
if [ -d "$VENV_DIR" ]; then
    if [ -f "$VENV_DIR/bin/activate" ]; then
        source "$VENV_DIR/bin/activate"
        PYTHON_CMD="$VENV_DIR/bin/python"
    else
        echo "Error: Virtual environment found but activate script missing"
        exit 1
    fi
else
    # Fallback to system Python
    if ! command -v python &> /dev/null && ! command -v python3 &> /dev/null; then
        echo "Error: Python is not installed or not in PATH"
        exit 1
    fi
    
    PYTHON_CMD="python3"
    if ! command -v python3 &> /dev/null; then
        PYTHON_CMD="python"
    fi
fi

# Check requirements
REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"
if [ -f "$REQUIREMENTS_FILE" ]; then
    echo "Checking dependencies..."
    if ! $PYTHON_CMD -c "import openai" 2>/dev/null; then
        echo "Dependencies not installed. Installing from requirements.txt..."
        $PYTHON_CMD -m pip install -r "$REQUIREMENTS_FILE"
        if [ $? -ne 0 ]; then
            echo "Error: Failed to install dependencies"
            exit 1
        fi
    fi
fi

# Check if profile argument is provided
if [ $# -eq 0 ]; then
    echo "Usage: ./migrate.sh <profile>"
    echo ""
    echo "Example:"
    echo "  ./migrate.sh hy"
    echo ""
    echo "For more information, see migration/README.md"
    exit 1
fi

# Run the migrator
echo "Running Seelenmaschine Migration Tool..."
echo ""
exec "$PYTHON_CMD" "$MIGRATOR" "$@"
