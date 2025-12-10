#!/bin/bash

# 检查是否提供了 profile 参数
if [ -z "$1" ]; then
    echo "错误: 请提供 profile 参数"
    echo "用法: ./start-flask-webui.sh <profile> [--host HOST] [--port PORT]"
    echo "示例: ./start-flask-webui.sh dev"
    echo "示例: ./start-flask-webui.sh dev --host 0.0.0.0 --port 8080"
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    echo "Installing dependencies..."
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi

echo "启动 Seelenmaschine Flask Web UI..."
cd src
python3 main.py "$@" --flask
