# bridge.py
import subprocess
import json
import threading
import sys
import time
import logging
import os
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler

# 获取脚本目录，用于存放日志文件
script_dir = Path(__file__).parent.absolute()
log_file = script_dir / "logs" / f"bridge_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
os.makedirs(script_dir / "logs", exist_ok=True)

# 配置 logging 输出到文件
logging.basicConfig(
    level=logging.INFO,  # Can be changed to DEBUG to see details
    format="%(asctime)s [%(levelname)s] %(threadName)s: %(message)s",
    handlers=[
        RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,  # 保留5个备份文件
            encoding='utf-8'
        )
    ]
)
logger = logging.getLogger(__name__)
logger.info(f"📝 Logging to file: {log_file}")


class MCPBridge:
    def __init__(self, server_cmd=None):
        # Get the directory where this script is located
        script_dir = Path(__file__).parent.absolute()
        narrator_path = script_dir / "narrator.py"

        # Use default command if not provided
        if server_cmd is None:
            server_cmd = ["python", str(narrator_path)]

        logger.info(f"🚀 Starting MCP Server subprocess...")
        logger.info(f"📁 Script directory: {script_dir}")
        logger.info(f"📄 Narrator path: {narrator_path}")

        self.proc = subprocess.Popen(
            server_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=str(script_dir)  # Set working directory to script's directory
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
    import pty
    import select
    import termios
    import tty
    import signal

    logger.info("🧩 Starting MCP Bridge...")
    bridge = MCPBridge()
    time.sleep(0.5)

    # 创建一个伪终端对
    master_fd, slave_fd = pty.openpty()

    # 获取终端名称
    slave_name = os.ttyname(slave_fd)
    logger.info(f"📺 Created PTY: {slave_name}")

    # 保存当前终端设置
    old_settings = termios.tcgetattr(sys.stdin)

    # 在伪终端中运行 Claude
    claude_cmd = ["claude"]  # 或者从命令行参数获取
    claude_proc = subprocess.Popen(
        claude_cmd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        start_new_session=True
    )

    # 关闭 slave_fd（master 端保持打开）
    os.close(slave_fd)

    # 设置终端为原始模式（用于正确处理输入）
    try:
        tty.setraw(sys.stdin.fileno())

        def restore_terminal():
            """恢复终端设置"""
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

        # 注册信号处理，确保退出时恢复终端
        def signal_handler(sig, frame):
            restore_terminal()
            os.close(master_fd)
            if claude_proc.poll() is None:
                claude_proc.terminate()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # 双向通信循环
        try:
            while True:
                # 检查哪些文件描述符有数据可读
                ready, _, _ = select.select([master_fd, sys.stdin], [], [], 0.1)

                # 从 Claude 的输出（master_fd）读取
                if master_fd in ready:
                    try:
                        data = os.read(master_fd, 1024)
                        if not data:
                            break

                        # 输出到终端
                        sys.stdout.buffer.write(data)
                        sys.stdout.buffer.flush()

                        # 处理文本内容，发送给 bridge
                        try:
                            text = data.decode('utf-8', errors='replace')
                            for line in text.splitlines(keepends=True):
                                clean = clean_text(line)
                                if clean:
                                    bridge.send_chunk(clean)
                        except Exception as e:
                            logger.debug(f"Error processing text: {e}")
                    except OSError:
                        break

                # 从用户输入（stdin）读取，转发给 Claude
                if sys.stdin in ready:
                    try:
                        data = os.read(sys.stdin.fileno(), 1024)
                        if not data:
                            break
                        # 转发给 Claude
                        os.write(master_fd, data)
                    except OSError:
                        break

                # 检查进程是否结束
                if claude_proc.poll() is not None:
                    # 读取剩余数据
                    while True:
                        ready, _, _ = select.select([master_fd], [], [], 0.1)
                        if not ready:
                            break
                        try:
                            data = os.read(master_fd, 1024)
                            if not data:
                                break
                            sys.stdout.buffer.write(data)
                            sys.stdout.buffer.flush()
                        except OSError:
                            break
                    break

        except KeyboardInterrupt:
            logger.info("⚠️ Interrupted by user")
        finally:
            restore_terminal()

    finally:
        os.close(master_fd)
        if claude_proc.poll() is None:
            claude_proc.terminate()
        claude_proc.wait()

        # 等待所有响应
        logger.info("⏳ Waiting for MCP Server responses...")
        bridge.wait_for_responses(timeout=2.0)
        logger.info("✅ All responses received (or timeout)")
