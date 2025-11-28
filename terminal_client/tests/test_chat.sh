#!/bin/bash
# Interactive chat test with vibe-narrator

set -e

# Get project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo "❌ Missing .env file"
    echo "Run: cp .env.example .env (then add your API key)"
    exit 1
fi

cd "$PROJECT_ROOT"
source .env
if [ -z "$OPENAI_API_KEY" ]; then
    echo "❌ OPENAI_API_KEY not set in .env"
    exit 1
fi

echo "🎤 Starting interactive chat with vibe-narrator"
echo ""
echo "Notes:"
echo "  - Type your messages and press Enter"
echo "  - AI responses will be spoken (not printed)"
echo "  - Use /quit to exit"
echo ""
echo "Starting in 2 seconds..."
sleep 2

# Run chat through bridge
uv run python narrator-client/bridge.py python narrator-client/chat.py
