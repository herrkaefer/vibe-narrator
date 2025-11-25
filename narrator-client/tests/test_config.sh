#!/bin/bash
# Simple test script to verify bridge configuration

# Get project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "Testing vibe-narrator configuration..."
echo ""

# Check if .env exists
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo "❌ .env file not found"
    echo "Please create it from .env.example:"
    echo "  cp .env.example .env"
    echo "  # Then edit .env and add your OpenAI API key"
    exit 1
fi

cd "$PROJECT_ROOT"

# Check if OPENAI_API_KEY is set in .env
if ! grep -q "^OPENAI_API_KEY=" .env; then
    echo "❌ OPENAI_API_KEY not found in .env"
    echo "Please add your OpenAI API key to .env"
    exit 1
fi

# Check if API key looks valid (starts with sk-)
API_KEY=$(grep "^OPENAI_API_KEY=" .env | cut -d'=' -f2)
if [[ ! $API_KEY == sk-* ]]; then
    echo "⚠️  Warning: OPENAI_API_KEY doesn't start with 'sk-'"
    echo "Make sure you've set a valid OpenAI API key"
fi

echo "✅ .env file found with OPENAI_API_KEY"
echo ""
echo "Running test: echo 'Hello, this is a test'"
echo "Press Ctrl+C to stop"
echo ""
echo "----------------------------------------"

# Run the test
uv run python narrator-client/bridge.py echo "Hello, this is a test"

echo ""
echo "----------------------------------------"
echo ""
echo "Check the logs for details:"
echo "  Bridge log: $(ls -t narrator-client/logs/bridge_*.log 2>/dev/null | head -1)"
echo "  Narrator log: $(ls -t narrator-mcp/logs/narrator_*.log 2>/dev/null | head -1)"
