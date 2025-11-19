#!/bin/bash
# Interactive chat test with vibe-narrator

set -e

if [ ! -f .env ]; then
    echo "❌ Missing .env file"
    echo "Run: cp .env.example .env (then add your API key)"
    exit 1
fi

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
uv run python bridge.py python chat.py
