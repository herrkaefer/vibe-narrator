#!/usr/bin/env python3
"""Test narration directly with MCP server"""
import subprocess
import json
import sys
import os
from pathlib import Path

# Load .env (look in project root)
test_dir = Path(__file__).parent
project_root = test_dir.parent.parent  # narrator-client -> project root
env_file = project_root / ".env"
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            if line.strip() and not line.startswith('#'):
                key, value = line.strip().split('=', 1)
                os.environ[key] = value

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("❌ OPENAI_API_KEY not set")
    sys.exit(1)

narrator_path = project_root / "narrator-mcp" / "server.py"

print("Starting MCP server...")
proc = subprocess.Popen(
    ["uv", "run", "python", str(narrator_path)],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    bufsize=1
)

def send_msg(msg):
    """Send a JSON-RPC message"""
    json_str = json.dumps(msg) + "\n"
    print(f">>> Sending: {msg['method']}")
    proc.stdin.write(json_str)
    proc.stdin.flush()

def read_response():
    """Read one response line"""
    line = proc.stdout.readline()
    if line:
        msg = json.loads(line)
        print(f"<<< Received: {json.dumps(msg, indent=2)}")
        return msg
    return None

try:
    # 1. Initialize
    send_msg({
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0.0"}
        }
    })
    resp = read_response()
    if not resp or "error" in resp:
        print("❌ Initialize failed")
        sys.exit(1)
    print("✅ Initialize OK")

    # 2. Send initialized notification
    send_msg({
        "jsonrpc": "2.0",
        "method": "notifications/initialized"
    })
    print("✅ Sent initialized notification")

    # 3. Config
    send_msg({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "config",
        "params": {
            "llm_api_key": api_key,
            "llm_model": "gpt-4o-mini",
            "voice": "alloy"
        }
    })
    resp = read_response()
    if not resp or "error" in resp:
        print(f"❌ Config failed: {resp}")
        sys.exit(1)
    print("✅ Config OK")

    # 4. Narrate a simple message
    print("\n🎤 Testing narration...")
    send_msg({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "narrate",
        "params": {
            "prompt": "Hello, this is a simple test message."
        }
    })

    # Read responses (may be multiple for events)
    print("\nWaiting for responses...")
    import time
    start_time = time.time()
    done = False

    while not done and (time.time() - start_time) < 30:
        # Check if process died
        if proc.poll() is not None:
            print(f"\n❌ Process died with code: {proc.returncode}")
            stderr = proc.stderr.read()
            if stderr:
                print("\nSTDERR:")
                print(stderr)
            break

        # Try to read stdout
        import select
        ready, _, _ = select.select([proc.stdout], [], [], 0.1)
        if ready:
            line = proc.stdout.readline()
            if line:
                try:
                    msg = json.loads(line)
                    print(f"<<< {json.dumps(msg)}")
                    if msg.get("id") == 2:
                        if "result" in msg:
                            print("\n✅ Narration completed!")
                            done = True
                        elif "error" in msg:
                            print(f"\n❌ Narration error: {msg['error']}")
                            done = True
                except json.JSONDecodeError:
                    print(f"Non-JSON: {line}")

    if not done:
        print("\n⚠️  Timeout waiting for narration to complete")

finally:
    print("\n🛑 Terminating server...")
    proc.terminate()
    proc.wait(timeout=2)
    stderr = proc.stderr.read()
    if stderr:
        print("\nServer STDERR:")
        print(stderr)
