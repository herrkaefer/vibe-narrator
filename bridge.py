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

        # Track pending requests to wait for responses
        self.pending_requests = {}  # id -> timestamp
        self.responses_received = {}  # id -> response

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
                # logger.info(f"🟢 MCP Server Response: {line}")
                msg = json.loads(line)

                # Check if it's an initialize response (id=0)
                if msg.get("id") == 0 and "result" in msg:
                    self.initialize_response = msg
                    self.initialize_event.set()
                    logger.info(f"✅ Received initialize response: {msg.get('result', {})}")

                # Track tool call responses
                response_id = msg.get("id")
                if response_id is not None:
                    self.responses_received[response_id] = msg
                    if response_id in self.pending_requests:
                        del self.pending_requests[response_id]
                    logger.info(f"🟢 MCP Server Response (id={response_id}): {msg}")

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
        self.pending_requests[req["id"]] = time.time()
        self._send(req)
        logger.info(f"📤 Sent text chunk to MCP Server: {text}")

    def wait_for_responses(self, timeout=5.0):
        """Wait for all pending requests to receive responses"""
        start_time = time.time()
        while self.pending_requests and (time.time() - start_time) < timeout:
            time.sleep(0.1)
        if self.pending_requests:
            logger.warning(f"⚠️ Still waiting for {len(self.pending_requests)} responses: {list(self.pending_requests.keys())}")


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
    import select  # For checking if stdin has data (Unix only)

    logger.info("🧩 Starting MCP Bridge...")
    logger.info("📥 Reading from stdin (use pipe: command | python bridge.py)")

    bridge = MCPBridge()

    # Wait a bit for MCP Server to be ready
    time.sleep(0.5)

    # Read from stdin line by line (supports piping from any command)
    try:
        # Check if stdin is a TTY (interactive) or pipe
        if sys.stdin.isatty():
            logger.warning("⚠️ stdin is a TTY (interactive terminal)")
            logger.info("💡 Usage: command | python bridge.py")
            logger.info("💡 Example: claude --help | python bridge.py")
            logger.info("💡 Or: echo 'test output' | python bridge.py")
        else:
            logger.info("✅ Reading from stdin pipe...")

        # Read from stdin line by line in real-time
        for line in sys.stdin:
            clean = clean_text(line)
            if clean:
                logger.debug(f"📥 Received line: {clean}")
                bridge.send_chunk(clean)

        logger.info("✅ Finished reading from stdin")

        # Wait for all responses before exiting
        logger.info("⏳ Waiting for MCP Server responses...")
        bridge.wait_for_responses(timeout=2.0)
        logger.info("✅ All responses received (or timeout)")

        # Give a small buffer for any final messages
        time.sleep(0.2)

    except KeyboardInterrupt:
        logger.info("⚠️ Interrupted by user")
    except BrokenPipeError:
        logger.warning("⚠️ Broken pipe (upstream command closed)")
    except Exception as e:
        logger.exception(f"❌ Error reading from stdin: {e}")
