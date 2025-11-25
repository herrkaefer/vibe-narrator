#!/bin/bash
# Diagnostic script for vibe-narrator setup

echo "=== Vibe Narrator Diagnostic Tool ==="
echo ""

# Check Python version
echo "1. Checking Python version..."
python3 --version
echo ""

# Check uv
echo "2. Checking uv installation..."
if command -v uv &> /dev/null; then
    uv --version
    echo "✅ uv is installed"
else
    echo "❌ uv is not installed"
    echo "Install from: https://github.com/astral-sh/uv"
fi
echo ""

# Check .env file
echo "3. Checking .env file..."
if [ -f .env ]; then
    echo "✅ .env file exists"
    if grep -q "^OPENAI_API_KEY=sk-" .env; then
        echo "✅ OPENAI_API_KEY is set and looks valid"
    else
        echo "⚠️  OPENAI_API_KEY may not be set correctly"
    fi
else
    echo "❌ .env file not found"
    echo "Run: cp .env.example .env"
fi
echo ""

# Check dependencies
echo "4. Checking Python dependencies..."
echo "  Checking narrator-mcp dependencies..."
if cd narrator-mcp && uv run python -c "import openai; import fastmcp; print('✅ MCP server dependencies OK')" 2>/dev/null; then
    :
else
    echo "  ❌ MCP server dependencies missing"
    echo "  Run: cd narrator-mcp && uv sync"
fi
cd ..
echo "  Checking narrator-client dependencies..."
if cd narrator-client && uv run python -c "import fastmcp; import httpx; import pyaudio; print('✅ Client dependencies OK')" 2>/dev/null; then
    :
else
    echo "  ❌ Client dependencies missing"
    echo "  Run: cd narrator-client && uv sync"
fi
cd ..
echo ""

# Check MCP server script
echo "5. Checking MCP server..."
if [ -f narrator-mcp/server.py ]; then
    echo "✅ narrator-mcp/server.py exists"
    # Test import
    if cd narrator-mcp && uv run python -c "import server; print('✅ MCP server imports successfully')" 2>/dev/null; then
        :
    else
        echo "❌ MCP server has import errors"
        cd narrator-mcp && uv run python -c "import server" 2>&1 | head -10
    fi
    cd ..
else
    echo "❌ narrator-mcp/server.py not found"
fi
echo ""

# Check logs directory
echo "6. Checking logs..."
if [ -d narrator-client/logs ]; then
    echo "✅ narrator-client/logs/ directory exists"
    echo "Recent bridge logs:"
    ls -lt narrator-client/logs/bridge_*.log 2>/dev/null | head -3 || echo "  (no logs yet)"
else
    echo "⚠️  narrator-client/logs/ directory doesn't exist (will be created on first run)"
fi
echo ""

if [ -d narrator-mcp/logs ]; then
    echo "✅ narrator-mcp/logs/ directory exists"
    echo "Recent narrator logs:"
    ls -lt narrator-mcp/logs/narrator_*.log 2>/dev/null | head -3 || echo "  (no logs yet)"
else
    echo "⚠️  narrator-mcp/logs/ directory doesn't exist (will be created on first run)"
fi
echo ""

echo "=== Diagnostic Complete ==="
echo ""
echo "Next steps:"
echo "  1. If .env is missing: cp .env.example .env (then edit with your API key)"
echo "  2. If dependencies are missing:"
echo "     - cd narrator-mcp && uv sync"
echo "     - cd narrator-client && uv sync"
echo "  3. Test MCP server: narrator-client/tests/test_mcp_only.sh"
echo "  4. Test full bridge: narrator-client/tests/test_config.sh"
