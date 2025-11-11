# bridge.py
import subprocess
import json
import threading
import sys
import time
import logging
import os
import re
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler

# Get script directory for storing log files
script_dir = Path(__file__).parent.absolute()
log_file = script_dir / "logs" / f"bridge_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
os.makedirs(script_dir / "logs", exist_ok=True)

# Configure logging output to file
logging.basicConfig(
    level=logging.INFO,  # Can be changed to DEBUG to see details
    format="%(asctime)s [%(levelname)s] %(threadName)s: %(message)s",
    handlers=[
        RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,  # Keep 5 backup files
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

                # Check if it's a notification (no id field)
                if "id" not in msg:
                    method = msg.get("method", "")
                    if method == "notifications/shutdown":
                        logger.info(f"🛑 Received shutdown notification from MCP Server: {msg.get('params', {})}")
                        # Can do some cleanup work here
                        continue

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
        logger.info(f"📤 Sent text chunk to MCP Server:\n{text}")

    def wait_for_responses(self, timeout=5.0):
        """Wait for all pending requests to receive responses"""
        start_time = time.time()
        while self.pending_requests and (time.time() - start_time) < timeout:
            time.sleep(0.1)
        if self.pending_requests:
            logger.warning(f"⚠️ Still waiting for {len(self.pending_requests)} responses: {list(self.pending_requests.keys())}")

    def cleanup(self):
        """Clean up MCP Server process"""
        if self.proc.poll() is None:
            logger.info("🛑 Terminating MCP Server process...")
            self.proc.terminate()

            # Give MCP Server some time to send shutdown notification
            import time
            time.sleep(0.2)

            try:
                self.proc.wait(timeout=1.8)  # Total 2 seconds, already waited 0.2 seconds
            except subprocess.TimeoutExpired:
                logger.warning("⚠️ MCP Server didn't terminate, forcing kill...")
                self.proc.kill()
                self.proc.wait()
            logger.info("✅ MCP Server process terminated")
        else:
            logger.info(f"✅ MCP Server process already exited (code: {self.proc.returncode})")


def clean_ansi_codes(text: str) -> str:
    """
    Clean ANSI escape sequences (color codes, formatting characters, etc.), restore plain text

    Removed ANSI sequences include:
    - Color codes: \x1b[30m - \x1b[37m (foreground), \x1b[40m - \x1b[47m (background)
    - Style codes: \x1b[0m (reset), \x1b[1m (bold), \x1b[2m (dim), etc.
    - Cursor control: \x1b[K (clear to end of line), \x1b[J (clear screen), etc.
    - DEC private mode sequences: \x1b[?number h/l (e.g. [?25l, [?2004h etc.)
    - OSC sequences: \x1b]number;...\x07 or \x1b]number;...\x1b\\ (e.g. ]0;title, ]9;command)
    - General format: \x1b[...m or \033[...m

    Args:
        text: Text containing ANSI escape sequences

    Returns:
        Cleaned plain text
    """
    if not text:
        return text

    # Remove OSC (Operating System Command) sequences
    # Full format: \x1b]number;text\x07 or \x1b]number;text\x1b\\
    # But may be split, leaving only ]number;text or ]number;
    osc_patterns = [
        r'\x1b\]\d+;.*?(\x07|\x1b\\)',  # Complete OSC sequence (with prefix)
        r'\033\]\d+;.*?(\x07|\x1b\\)',  # Octal form
        r'\]\d+;.*?(\x07|\x1b\\)',      # OSC sequence with prefix removed (with ending)
        r'\]\d+;[^\n]*',                 # OSC sequence with both prefix and ending removed (]number; to end of line)
    ]

    # Remove all ANSI escape sequences (including DEC private mode and OSC)
    ansi_patterns = [
        r'\x1b\[[0-9;]*[a-zA-Z]',           # Standard ANSI sequence
        r'\x1b\[[?][0-9;]*[hHlL]',          # DEC private mode sequence
        r'\033\[[0-9;]*[a-zA-Z]',            # Standard ANSI sequence (octal)
        r'\033\[[?][0-9;]*[hHlL]',           # DEC private mode sequence (octal)
        r'\[[?][0-9;]*[hHlL]',               # Standalone DEC private mode sequence
        r'\[[0-9;]*[a-zA-Z]',                 # Standalone ANSI sequence
        r'\[[0-9;]+',                         # Incomplete ANSI sequence (e.g. [38;2;102;102)
        r'^[;0-9]+m',                         # Continuation of sequence (e.g. ;102m)
    ] + osc_patterns

    # Combine all patterns
    ansi_escape = re.compile('|'.join(ansi_patterns))
    text = ansi_escape.sub('', text)

    # Remove other common control characters (but keep useful ones like newlines, tabs)
    # Remove backspace, carriage return (when standalone), bell, etc.
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

    # Remove garbled characters (replacement character U+FFFD)
    text = text.replace('\ufffd', '')
    # Remove other invalid Unicode characters
    text = re.sub(r'[\u200b-\u200f\u202a-\u202e\ufeff]', '', text)

    return text


import unicodedata

def filter_ui_elements(text: str) -> str:
    """
    Keep only natural language characters, filter out all special characters, icons, UI elements, etc.

    Supports all human languages: Chinese, Japanese, French, German, English, etc.
    """
    if not text:
        return ""

    lines = text.split('\n')
    filtered_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 1. Filter empty user input (lines starting with > but no content after)
        if line.startswith('>'):
            # Remove ">" and spaces after, check if there's any content
            content_after_arrow = line[1:].strip()
            if not content_after_arrow:
                continue

        # 2. Filter Claude Code prompts starting with question mark (e.g. "? for shortcuts")
        if line.startswith('?'):
            continue

        # 3. Filter remaining OSC sequences (e.g. "]0; Display Circle", "]9;")
        if re.match(r'^\]\d+;', line.strip()):
            continue

        # 4. Filter UI prompt text
        ui_patterns = [
            r'^Thinking on \(tab to toggle\)',
            r'^\(esc to interrupt\)',
            r'^\(esc to interrupt',
            r'^Thought for \d+s',
            r'^ctrl\+o to show thinking',
            r'^ctrlo to show thinking',
            r'^Tip: Type',
            r'^Showing detailed transcript',
            r'^CtrlO to toggle',
            r'^accept edits on',
            r'^shift\+tab to cycle',
            r'^ctrl-g to edit prompt in vi',
        ]
        if any(re.match(pattern, line, re.IGNORECASE) for pattern in ui_patterns):
            continue

        # 5. Filter separator lines (mainly long lines of - or =)
        if len(line) > 20:
            line_chars = set(line.replace(' ', ''))
            separator_chars = set('-=─━')
            if line_chars.issubset(separator_chars) or \
               (len(line_chars & separator_chars) > 0 and len(line_chars - separator_chars) <= 2):
                continue

        # 6. Keep only natural language characters
        filtered_chars = []
        for char in line:
            cat = unicodedata.category(char)

            # Keep all letters (L* = Letter, includes all languages)
            if cat.startswith('L'):
                filtered_chars.append(char)
            # Keep all numbers (N* = Number)
            elif cat.startswith('N'):
                filtered_chars.append(char)
            # Keep spaces (Zs = Space Separator)
            elif cat == 'Zs':
                filtered_chars.append(char)
            # Keep pipe character (explicitly preserve to ensure not filtered)
            elif char == '|':
                filtered_chars.append(char)
            # Keep common text punctuation (P* = Punctuation, but needs filtering)
            elif cat.startswith('P'):
                # Keep common punctuation marks
                if char in '.,!?;:\'"()[]{}-_/\\@#$%&*+=<>|~`^…—–«»„"':
                    filtered_chars.append(char)
                # Keep Chinese punctuation range
                elif '\u3000' <= char <= '\u303f' or '\uff00' <= char <= '\uffef':
                    filtered_chars.append(char)
            # Temporarily keep separator characters (for pattern checking)
            elif char in '-=─━':
                filtered_chars.append(char)
            # Temporarily keep > character (for checking user input)
            elif char == '>':
                filtered_chars.append(char)

        line = ''.join(filtered_chars)

        # 7. Clean excessive whitespace
        line = re.sub(r'\s+', ' ', line).strip()

        if line:
            filtered_lines.append(line)

    return '\n'.join(filtered_lines)

def clean_text(text: str) -> str:
    """
    Clean Claude Code output, remove ANSI escape sequences and excessive whitespace

    First clean ANSI codes, then remove leading/trailing whitespace, finally send to MCP
    """
    # return text # testing...

    if not text:
        return ""

    # First clean ANSI escape sequences
    cleaned = clean_ansi_codes(text)

    cleaned = filter_ui_elements(cleaned)

    # Remove leading/trailing whitespace
    cleaned = cleaned.strip()

    return cleaned


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


class TextBuffer:
    """
    Text buffer that accumulates data and records timestamps to determine when to send
    Ensures sending only at line boundaries, avoiding cutting in the middle of lines
    """
    def __init__(self, min_window_seconds=1.0, pause_threshold=2.0):
        self.buffer = ""  # Accumulated text data
        self.window_start_time = None  # Current window start time
        self.last_data_time = None  # Time of last data arrival
        self.min_window_seconds = min_window_seconds  # Minimum accumulation time: 1 second
        self.pause_threshold = pause_threshold  # Pause threshold: 2 seconds

    def add_data(self, text: str, current_time: float):
        """Add new data to buffer, record timestamp"""
        self.buffer += text
        if self.window_start_time is None:
            self.window_start_time = current_time
        self.last_data_time = current_time

    def has_complete_lines(self) -> bool:
        """Check if buffer has complete lines (ending with newline)"""
        return self.buffer and '\n' in self.buffer

    def should_flush(self, current_time: float) -> bool:
        """
        Determine if buffer should be flushed

        Returns True in the following cases:
        1. Buffer has complete lines and accumulation time >= minimum time window (1 second)
        2. Time since last data arrival exceeds pause threshold (2 seconds) and has complete lines
        3. Time since last data arrival exceeds pause threshold (2 seconds) and buffer is very large (send even without complete lines)
        """
        if not self.buffer:
            return False

        has_complete = self.has_complete_lines()

        # Check if minimum time window is exceeded (must have complete lines)
        if self.window_start_time and \
           (current_time - self.window_start_time) >= self.min_window_seconds:
            if has_complete:
                return True

        # Check if pause threshold is exceeded
        if self.last_data_time and \
           (current_time - self.last_data_time) >= self.pause_threshold:
            # Send if has complete lines, or buffer is very large (exceeds certain size)
            if has_complete or len(self.buffer) > 4096:
                return True

        return False

    def flush(self) -> str:
        """
        Flush buffer, return complete lines, keep incomplete lines in buffer

        Returns empty string if no complete lines to send
        """
        if not self.buffer:
            return ""

        # Find the position of the last newline
        last_newline = self.buffer.rfind('\n')

        if last_newline == -1:
            # No newline, don't send (unless buffer is very large, in pause threshold case)
            if len(self.buffer) > 4096:
                # Buffer is very large but no newline, possibly a very long single line, send all
                result = self.buffer
                self.buffer = ""
                self.window_start_time = None
                self.last_data_time = None
                return result
            return ""

        # Send complete lines up to the last newline
        result = self.buffer[:last_newline + 1]  # Include newline
        self.buffer = self.buffer[last_newline + 1:]  # Keep incomplete lines

        # If buffer is cleared, reset timestamps
        if not self.buffer:
            self.window_start_time = None
            self.last_data_time = None
        else:
            # If there's remaining data, update window start time (start counting from remaining data)
            self.window_start_time = time.time()

        return result

    def has_data(self) -> bool:
        """Check if buffer has data"""
        return bool(self.buffer)

    def flush_all(self) -> str:
        """
        Force flush all buffer contents (used when program ends)
        Send even if there are no complete lines
        """
        if not self.buffer:
            return ""

        result = self.buffer
        self.buffer = ""
        self.window_start_time = None
        self.last_data_time = None
        return result


if __name__ == "__main__":
    import pty
    import select
    import termios
    import tty
    import signal
    import argparse

    parser = argparse.ArgumentParser(
        description='MCP Bridge - Run command in PTY and forward output to MCP server',
        epilog='''
Examples:
  python bridge.py claude
  python bridge.py python -i
  python bridge.py bash
        '''
    )
    parser.add_argument('command', nargs=argparse.REMAINDER,
                       help='Command to run in PTY (e.g., claude, python -i, bash)')
    args = parser.parse_args()

    if not args.command:
        parser.error("command is required")

    logger.info("🧩 Starting MCP Bridge...")
    bridge = MCPBridge()
    time.sleep(0.5)

    # Create a pseudo terminal pair
    master_fd, slave_fd = pty.openpty()

    # Get terminal name
    slave_name = os.ttyname(slave_fd)
    logger.info(f"📺 Created PTY: {slave_name}")

    # Save current terminal settings
    old_settings = termios.tcgetattr(sys.stdin)

    # Get command to run from command line arguments
    cmd = args.command
    logger.info(f"🚀 Running command in PTY: {' '.join(cmd)}")

    cmd_proc = subprocess.Popen(
        cmd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        start_new_session=True
    )

    # Close slave_fd (master side remains open)
    os.close(slave_fd)

    # Set terminal to raw mode (for proper input handling)
    try:
        tty.setraw(sys.stdin.fileno())

        def restore_terminal():
            """Restore terminal settings"""
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

        # Register signal handler to ensure terminal is restored on exit
        def signal_handler(sig, frame):
            restore_terminal()
            os.close(master_fd)
            if cmd_proc.poll() is None:
                cmd_proc.terminate()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Initialize text buffer
        text_buffer = TextBuffer(min_window_seconds=1.0, pause_threshold=2.0)

        # Bidirectional communication loop
        try:
            while True:
                current_time = time.time()

                # Check if buffer should be flushed (even if there's no new data)
                if text_buffer.should_flush(current_time):
                    buffered_text = text_buffer.flush()
                    if buffered_text:
                        clean = clean_text(buffered_text)
                        if clean:
                            bridge.send_chunk(clean)

                # Check which file descriptors have data to read
                ready, _, _ = select.select([master_fd, sys.stdin], [], [], 0.1)

                # Read from command output (master_fd)
                if master_fd in ready:
                    try:
                        data = os.read(master_fd, 1024)
                        if not data:
                            break

                        # Output to terminal
                        sys.stdout.buffer.write(data)
                        sys.stdout.buffer.flush()

                        # Add to buffer (don't process immediately)
                        try:
                            text = data.decode('utf-8', errors='replace')
                            current_time = time.time()
                            text_buffer.add_data(text, current_time)

                            # Check if should flush
                            if text_buffer.should_flush(current_time):
                                buffered_text = text_buffer.flush()
                                if buffered_text:
                                    clean = clean_text(buffered_text)
                                    if clean:
                                        bridge.send_chunk(clean)
                        except Exception as e:
                            logger.debug(f"Error processing text: {e}")
                    except OSError:
                        break

                # Read from user input (stdin), forward to command
                if sys.stdin in ready:
                    try:
                        data = os.read(sys.stdin.fileno(), 1024)
                        if not data:
                            break
                        # Forward to command
                        os.write(master_fd, data)
                    except OSError:
                        break

                # Check if process has ended
                if cmd_proc.poll() is not None:
                    # Read remaining data
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

                            # Add to buffer
                            text = data.decode('utf-8', errors='replace')
                            current_time = time.time()
                            text_buffer.add_data(text, current_time)
                        except OSError:
                            break

                    # Process remaining buffer
                    buffered_text = text_buffer.flush_all()
                    if buffered_text:
                        clean = clean_text(buffered_text)
                        if clean:
                            bridge.send_chunk(clean)
                    break

        except KeyboardInterrupt:
            logger.info("⚠️ Interrupted by user")
        finally:
            restore_terminal()

            # Process final remaining buffer
            if text_buffer.has_data():
                buffered_text = text_buffer.flush_all()
                if buffered_text:
                    clean = clean_text(buffered_text)
                    if clean:
                        bridge.send_chunk(clean)

    finally:
        os.close(master_fd)
        if cmd_proc.poll() is None:
            cmd_proc.terminate()
        cmd_proc.wait()

        # Clean up MCP Server
        bridge.cleanup()

        # Wait for all responses
        bridge.wait_for_responses(timeout=2.0)
        logger.info("✅ All responses received (or timeout)")
