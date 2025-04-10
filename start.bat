@echo off
IF NOT EXIST ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    call .\.venv\Scripts\activate.bat
    echo Installing dependencies...
    pip install -r requirements.txt
) ELSE (
    call .\.venv\Scripts\activate.bat
)

python src\main.py
