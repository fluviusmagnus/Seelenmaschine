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

echo 启动 Seelenmaschine Flask Web UI...
cd src
python main.py --flask --host 127.0.0.1 --port 7860
pause
