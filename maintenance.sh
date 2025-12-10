#!/bin/bash

# Seelenmaschine数据库维护脚本
# 使用方法：
#   ./maintenance.sh <profile> [options]
#   选项：--all, --sqlite, --lancedb, --dry-run, --verbose
#   ./maintenance.sh help - 显示帮助

set -e  # 遇到错误时退出

echo "========================================"
echo "Seelenmaschine 数据库维护工具"
echo "========================================"
echo

# 检查是否提供了 profile 参数
if [ "$1" = "help" ] || [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "使用方法："
    echo "  ./maintenance.sh <profile> [options]"
    echo ""
    echo "必需参数："
    echo "  <profile>              配置文件名（如 dev, production）"
    echo ""
    echo "可选参数："
    echo "  --all                  维护所有数据库（默认）"
    echo "  --sqlite               只维护SQLite数据库"
    echo "  --lancedb              只维护LanceDB数据库"
    echo "  --dry-run              干运行模式（预览操作，不实际执行）"
    echo "  --verbose, -v          详细输出模式"
    echo ""
    echo "示例："
    echo "  ./maintenance.sh dev"
    echo "  ./maintenance.sh dev --all"
    echo "  ./maintenance.sh dev --sqlite --dry-run"
    echo "  ./maintenance.sh dev --lancedb --verbose"
    echo "  ./maintenance.sh production --all --dry-run --verbose"
    exit 0
fi

if [ -z "$1" ]; then
    echo "错误: 请提供 profile 参数"
    echo "用法: ./maintenance.sh <profile> [options]"
    echo "示例: ./maintenance.sh dev --sqlite --dry-run"
    echo "使用 './maintenance.sh help' 查看详细帮助"
    exit 1
fi

PROFILE="$1"
shift  # 移除第一个参数

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
PYTHON_ARGS=""
HAS_MODE=false

while [ $# -gt 0 ]; do
    case "$1" in
        --all|--sqlite|--lancedb)
            PYTHON_ARGS="$PYTHON_ARGS $1"
            HAS_MODE=true
            shift
            ;;
        --dry-run|-v|--verbose)
            PYTHON_ARGS="$PYTHON_ARGS $1"
            shift
            ;;
        *)
            echo "未知参数: $1"
            echo "使用 './maintenance.sh help' 查看帮助"
            exit 1
            ;;
    esac
done

# 如果没有指定数据库选择，默认使用 --all
if [ "$HAS_MODE" = false ]; then
    PYTHON_ARGS="--all $PYTHON_ARGS"
fi

echo "Profile: $PROFILE"
echo "参数: $PYTHON_ARGS"
echo
echo "开始数据库维护..."
echo

# 执行维护脚本
if $PYTHON_CMD database_maintenance.py "$PROFILE" $PYTHON_ARGS; then
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
