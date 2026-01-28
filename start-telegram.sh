#!/bin/bash
if [ -z "$1" ]; then
    echo "Usage: $0 <profile>"
    exit 1
fi

python src/main_telegram.py "$1"
