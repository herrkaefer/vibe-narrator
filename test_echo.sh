#!/bin/bash
# Quick test with echo command

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

echo "🎤 Testing vibe-narrator with echo command"
echo "=========================================="
echo ""
echo "Command: echo 'Hello from vibe-narrator!'"
echo ""
echo "What will happen:"
echo "  1. Echo will print the message"
echo "  2. Bridge will capture the text"
echo "  3. MCP server will generate speech"
echo "  4. Audio events will be sent back to bridge"
echo "  5. Program waits for completion before exiting"
echo ""
echo "Starting..."
echo ""
echo "----------------------------------------"

uv run python bridge.py echo "Hello from vibe-narrator!"

echo "----------------------------------------"
echo ""
echo "✅ Test complete!"
echo ""
echo "Check logs for details:"
BRIDGE_LOG=$(ls -t logs/bridge_*.log 2>/dev/null | head -1)
NARRATOR_LOG=$(ls -t narrator-mcp/logs/narrator_*.log 2>/dev/null | head -1)

if [ -n "$BRIDGE_LOG" ]; then
    echo "  Bridge: $BRIDGE_LOG"
    echo ""
    echo "Bridge status:"
    tail -20 "$BRIDGE_LOG" | grep -E "(✅|❌|⏳|📤|🎧|🔊|📊)" || echo "  (no status messages)"
fi

echo ""

if [ -n "$NARRATOR_LOG" ]; then
    echo "  Narrator: $NARRATOR_LOG"
    echo ""
    echo "Narrator log:"
    cat "$NARRATOR_LOG"
fi
