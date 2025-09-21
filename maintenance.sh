#!/bin/bash

# Seelenmaschine数据库维护脚本
# 使用方法：
#   ./maintenance.sh          - 完整维护（默认）
#   ./maintenance.sh dry      - 干运行模式
#   ./maintenance.sh sqlite   - 只维护SQLite
#   ./maintenance.sh lancedb  - 只维护LanceDB
#   ./maintenance.sh help     - 显示帮助

set -e  # 遇到错误时退出

echo "========================================"
echo "Seelenmaschine 数据库维护工具"
echo "========================================"
echo

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    echo "Installing dependencies..."
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi

# 检查Python是否可用
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "错误：未找到Python，请确保Python已安装"
    exit 1
fi

# 优先使用python3，如果不存在则使用python
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
else
    PYTHON_CMD="python"
fi

# 检查维护脚本是否存在
if [ ! -f "database_maintenance.py" ]; then
    echo "错误：未找到database_maintenance.py文件"
    exit 1
fi

# 解析命令行参数
MODE="--all"
EXTRA_ARGS=""

case "${1:-}" in
    "help")
        $PYTHON_CMD database_maintenance.py --help
        exit 0
        ;;
    "dry")
        EXTRA_ARGS="--dry-run"
        echo "运行模式：干运行（预览模式）"
        ;;
    "sqlite")
        MODE="--sqlite"
        echo "运行模式：只维护SQLite数据库"
        ;;
    "lancedb")
        MODE="--lancedb"
        echo "运行模式：只维护LanceDB数据库"
        ;;
    "")
        echo "运行模式：完整维护（SQLite + LanceDB）"
        ;;
    *)
        echo "未知参数: $1"
        echo "使用 './maintenance.sh help' 查看帮助"
        exit 1
        ;;
esac

echo
echo "开始数据库维护..."
echo

# 执行维护脚本
if $PYTHON_CMD database_maintenance.py $MODE $EXTRA_ARGS --verbose; then
    echo
    echo "========================================"
    echo "数据库维护成功完成！"
    echo "========================================"
else
    echo
    echo "========================================"
    echo "维护过程中出现错误！"
    echo "请检查上面的错误信息"
    echo "========================================"
    exit 1
fi
