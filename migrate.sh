#!/bin/bash
# Seelenmaschine Migration Tool Wrapper
# Quick wrapper for running the unified migration tool

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
MIGRATOR="$SCRIPT_DIR/migration/migrator.py"

# Check if Python is available
if ! command -v python &> /dev/null && ! command -v python3 &> /dev/null; then
    echo "Error: Python is not installed or not in PATH"
    exit 1
fi

# Use python3 if available, otherwise python
PYTHON_CMD="python3"
if ! command -v python3 &> /dev/null; then
    PYTHON_CMD="python"
fi

# Check if profile argument is provided
if [ $# -eq 0 ]; then
    echo "Usage: ./migrate.sh <profile> [options]"
    echo ""
    echo "Options:"
    echo "  --auto       Automatically run all needed migrations"
    echo "  --force      Force re-run migrations"
    echo "  --no-backup  Skip automatic backup (not recommended)"
    echo ""
    echo "Examples:"
    echo "  ./migrate.sh test              # Interactive mode"
    echo "  ./migrate.sh test --auto       # Auto-detect and migrate"
    echo "  ./migrate.sh test --force      # Force migration"
    echo ""
    echo "For more information, see MIGRATION_GUIDE.md"
    exit 1
fi

# Run the migrator
echo "Running Seelenmaschine Migration Tool..."
echo ""
exec "$PYTHON_CMD" "$MIGRATOR" "$@"
