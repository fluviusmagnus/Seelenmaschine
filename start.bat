@echo off

REM 检查是否提供了 profile 参数
IF "%1"=="" (
    echo 错误: 请提供 profile 参数
    echo 用法: start.bat ^<profile^>
    echo 示例: start.bat dev
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

python src\main.py %1
