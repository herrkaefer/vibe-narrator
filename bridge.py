# bridge.py
import subprocess
import json
import threading
import sys
import time
import logging

logging.basicConfig(
    level=logging.INFO,  # Can be changed to DEBUG to see details
    format="%(asctime)s [%(levelname)s] %(threadName)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger(__name__)


class MCPBridge:
    def __init__(self, server_cmd=["python", "narrator.py"]):
        logger.info("🚀 Starting MCP Server subprocess...")
        self.proc = subprocess.Popen(
            server_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        logger.info(f"✅ MCP Server process started (PID: {self.proc.pid})")

        # Synchronization mechanism for waiting for initialize response
        self.initialize_event = threading.Event()
        self.initialize_response = None

        # Listening threads
        threading.Thread(target=self._listen_stdout, name="ServerStdout", daemon=True).start()
        threading.Thread(target=self._listen_stderr, name="ServerStderr", daemon=True).start()

        # Initialize handshake - requires correct MCP parameters
        self._send({
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "bridge",
                    "version": "1.0.0"
                }
            }
        })
        logger.info("🤝 Sent MCP initialize request")

        # Wait for initialize response then send initialized notification
        if self.initialize_event.wait(timeout=5.0):
            logger.info("✅ Received initialize response, sending initialized notification")
            self._send({
                "jsonrpc": "2.0",
                "method": "notifications/initialized"
            })
            logger.info("✅ Sent initialized notification")
        else:
            logger.error("❌ Timeout waiting for initialize response")

    def _send(self, msg: dict):
        """Send JSON-RPC request to MCP Server"""
        try:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
            logger.debug(f"➡️ Sent to MCP Server: {msg}")
        except Exception as e:
            logger.exception(f"❌ Failed to send message: {e}")

    def _listen_stdout(self):
        """Listen to MCP Server's stdout (JSON responses)"""
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)

                # Check if it's an initialize response (id=0)
                if msg.get("id") == 0 and "result" in msg:
                    self.initialize_response = msg
                    self.initialize_event.set()
                    logger.info(f"✅ Received initialize response: {msg.get('result', {})}")

                logger.info(f"🟢 MCP Server Response: {msg}")
            except json.JSONDecodeError:
                logger.warning(f"⚠️ Non-JSON output from MCP Server: {line}")

    def _listen_stderr(self):
        """Listen to MCP Server's stderr (logs)"""
        for line in self.proc.stderr:
            logger.debug(f"🔴 MCP Server Log: {line.strip()}")

    def send_chunk(self, text):
        """Send text chunks to MCP Server - use tools/call to call tool"""
        req = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000),
            "method": "tools/call",
            "params": {
                "name": "narrate",
                "arguments": {
                    "text": text
                }
            }
        }
        self._send(req)
        logger.info(f"📤 Sent text chunk to MCP Server: {text}")


def clean_text(line: str) -> str:
    """Simple cleanup of Claude Code output (extensible)"""
    return line.strip()


def simulate_coding_output():
    """Simulate Claude Code output, can be replaced with real subprocess stdout listening"""
    samples = [
        "Compiling project...",
        "Running tests...",
        "✅ All tests passed!",
        "Deployment complete."
    ]
    for s in samples:
        yield s
        time.sleep(1)


if __name__ == "__main__":
    logger.info("🧩 Starting MCP Bridge...")
    bridge = MCPBridge()

    # Simulate real-time output (will be replaced with Claude Code real-time stdout in the future)
    for line in simulate_coding_output():
        clean = clean_text(line)
        if clean:
            logger.debug(f"➡️ Cleaned line: {clean}")
            bridge.send_chunk(clean)
