@echo off

REM 检查是否提供了 profile 参数
IF "%1"=="" (
    echo 错误: 请提供 profile 参数
    echo 用法: start-flask-webui.bat ^<profile^> [--host HOST] [--port PORT]
    echo 示例: start-flask-webui.bat dev
    echo 示例: start-flask-webui.bat dev --host 0.0.0.0 --port 8080
    pause
    exit /b 1
)

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
python main.py %* --flask
pause
