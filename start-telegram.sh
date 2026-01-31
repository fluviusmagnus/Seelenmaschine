#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
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
    PYTHON_CMD="python"
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

if [ -z "$1" ]; then
    echo "Usage: $0 <profile>"
    exit 1
fi

$PYTHON_CMD src/main_telegram.py "$1"
