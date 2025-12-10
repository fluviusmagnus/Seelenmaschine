#!/bin/bash

# 检查是否提供了 profile 参数
if [ -z "$1" ]; then
    echo "错误: 请提供 profile 参数"
    echo "用法: ./start.sh <profile>"
    echo "示例: ./start.sh dev"
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

python3 src/main.py "$1"
