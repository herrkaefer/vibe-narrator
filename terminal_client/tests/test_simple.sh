#!/bin/bash
# Simple test to verify bridge works

set -e

# Get project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "Simple Bridge Test"
echo "=================="
echo ""

# Check .env
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo "❌ Missing .env file"
    echo "Run: cp .env.example .env (then add your API key)"
    exit 1
fi

cd "$PROJECT_ROOT"
source .env
if [ -z "$OPENAI_API_KEY" ]; then
    echo "❌ OPENAI_API_KEY not set"
    exit 1
fi

echo "Running: echo 'Test message'"
echo ""
echo "The program will wait for narration to complete before exiting..."
echo ""

# Run without timeout - the bridge now handles waiting properly
uv run python narrator-client/bridge.py echo "Test message"
EXIT_CODE=$?

echo ""
echo "Exit code: $EXIT_CODE"

echo ""
echo "Check the most recent log:"
echo ""
LATEST_LOG=$(ls -t narrator-client/logs/bridge_*.log 2>/dev/null | head -1)
if [ -n "$LATEST_LOG" ]; then
    echo "=== Last 30 lines of $LATEST_LOG ==="
    tail -30 "$LATEST_LOG"
else
    echo "No log file found"
fi
