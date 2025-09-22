#!/bin/bash

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
python3 main.py --flask --host 127.0.0.1 --port 7860
