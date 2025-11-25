#!/bin/bash
# Quick test to verify audio events are received

set -e

# Get project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo "❌ Missing .env file"
    exit 1
fi

cd "$PROJECT_ROOT"
source .env
if [ -z "$OPENAI_API_KEY" ]; then
    echo "❌ OPENAI_API_KEY not set"
    exit 1
fi

echo "🎤 Quick Test: Checking audio event reception"
echo "=============================================="
echo ""

# Run a simple test
uv run python narrator-client/bridge.py echo "Quick test"

echo ""
echo "Checking for audio chunks in latest log..."
LATEST_LOG=$(ls -t narrator-client/logs/bridge_*.log 2>/dev/null | head -1)

if [ -n "$LATEST_LOG" ]; then
    AUDIO_COUNT=$(grep -c "🔊 Audio chunk" "$LATEST_LOG" || echo "0")
    TOKEN_COUNT=$(grep -c "📝 Text token" "$LATEST_LOG" || echo "0")

    echo ""
    echo "Results:"
    echo "  Audio chunks: $AUDIO_COUNT"
    echo "  Text tokens: $TOKEN_COUNT (in debug log)"
    echo ""

    if [ "$AUDIO_COUNT" -gt 0 ]; then
        echo "✅ SUCCESS! Audio events are being received!"
        echo ""
        echo "Sample audio chunks:"
        grep "🔊 Audio chunk" "$LATEST_LOG" | head -3
    else
        echo "❌ FAILED! No audio chunks received."
        echo ""
        echo "Last 20 lines of log:"
        tail -20 "$LATEST_LOG"
    fi
else
    echo "❌ No log file found"
fi
