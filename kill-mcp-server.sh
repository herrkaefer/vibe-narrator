#!/bin/bash
# kill-mcp-server.sh - Find and kill running MCP server processes

echo "🔍 Searching for MCP server processes..."

# Find processes using port 8000
PORT_PIDS=$(lsof -ti:8000 2>/dev/null)
if [ -n "$PORT_PIDS" ]; then
    echo "📌 Found processes using port 8000:"
    echo "$PORT_PIDS"
    for pid in $PORT_PIDS; do
        ps -p "$pid" -o pid,command
    done
else
    echo "✅ No processes found on port 8000"
fi

# Find narrator-mcp/server.py processes (more specific)
SERVER_PIDS=$(pgrep -f "narrator-mcp.*server.py" 2>/dev/null)
if [ -n "$SERVER_PIDS" ]; then
    echo ""
    echo "📌 Found narrator-mcp/server.py processes:"
    for pid in $SERVER_PIDS; do
        ps -p "$pid" -o pid,command
    done
else
    echo "✅ No narrator-mcp/server.py processes found"
fi

# Find narrator-mcp related processes
NARRATOR_PIDS=$(pgrep -f "narrator-mcp" 2>/dev/null)
if [ -n "$NARRATOR_PIDS" ]; then
    echo ""
    echo "📌 Found narrator-mcp related processes:"
    for pid in $NARRATOR_PIDS; do
        ps -p "$pid" -o pid,command
    done
else
    echo "✅ No narrator-mcp processes found"
fi

# Ask for confirmation if processes found
ALL_PIDS=$(echo "$PORT_PIDS $SERVER_PIDS $NARRATOR_PIDS" | tr ' ' '\n' | sort -u | grep -v '^$')

if [ -z "$ALL_PIDS" ]; then
    echo ""
    echo "✅ No MCP server processes found. Nothing to kill."
    exit 0
fi

echo ""
echo "⚠️  Found the following processes:"
for pid in $ALL_PIDS; do
    ps -p "$pid" -o pid,command 2>/dev/null || echo "  PID $pid (process may have exited)"
done

echo ""
read -p "Kill these processes? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    for pid in $ALL_PIDS; do
        if kill -0 "$pid" 2>/dev/null; then
            echo "🛑 Killing PID $pid..."
            kill "$pid"
            sleep 0.5
            if kill -0 "$pid" 2>/dev/null; then
                echo "   Force killing PID $pid..."
                kill -9 "$pid"
            fi
        fi
    done
    echo "✅ Done"
else
    echo "❌ Cancelled"
fi


