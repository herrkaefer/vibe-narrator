#!/bin/bash
# Test MCP server initialization and config

echo "Testing MCP Server initialization and config..."
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ .env file not found"
    echo "Please create it: cp .env.example .env"
    exit 1
fi

# Get API key from .env
source .env

if [ -z "$OPENAI_API_KEY" ]; then
    echo "❌ OPENAI_API_KEY not set in .env"
    exit 1
fi

echo "✅ Found OPENAI_API_KEY"
echo ""
echo "Sending initialize and config messages to MCP server..."
echo ""

# Get project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_ROOT/narrator-mcp"

# Create a test input with initialize, initialized notification, and config
cat <<EOF | uv run python server.py 2>&1 | tee /tmp/mcp_test.log
{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0.0"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":1,"method":"config","params":{"api_key":"$OPENAI_API_KEY","model":"gpt-4o-mini","voice":"alloy"}}
EOF

echo ""
echo "----------------------------------------"
echo ""
echo "Check the log output above for:"
echo "  ✅ Initialize response (id=0)"
echo "  ✅ Client sent initialized notification"
echo "  ✅ Config response (id=1)"
echo "  ✅ Session configured"
