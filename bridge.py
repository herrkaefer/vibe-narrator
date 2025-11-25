# bridge.py
import subprocess
import json
import threading
import sys
import time
import logging
import os
import re
import fcntl
import struct
import shutil
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler
import unicodedata
from dotenv import load_dotenv
from audio_player import AudioPlayer


class _AnsiCleaner:
    """Stateful ANSI escape sequence stripper."""

    def __init__(self):
        self.state = 'text'

    def reset(self):
        self.state = 'text'

    def clean(self, text: str) -> str:
        result = []
        state = self.state

        for ch in text:
            code = ord(ch)

            if state == 'text':
                if ch == '\x1b':
                    state = 'esc'
                    continue
                if code == 0x9b:  # single-byte CSI
                    state = 'csi'
                    continue
                if code in (0x90, 0x98, 0x9e, 0x9f):  # DCS, SOS, PM, APC
                    state = 'string'
                    continue
                if code == 0x9d:  # OSC
                    state = 'osc'
                    continue
                if code < 0x20 and ch not in ('\n', '\t'):
                    continue
                result.append(ch)
                continue

            if state == 'esc':
                if ch == '[':
                    state = 'csi'
                elif ch == ']':
                    state = 'osc'
                elif ch in ('P', 'X', '^', '_'):
                    state = 'string'
                elif ch == '\\':
                    state = 'text'
                elif ' ' <= ch <= '/':
                    state = 'esc_inter'
                else:
                    # Any final byte (including single-char ESC sequences)
                    state = 'text'
                continue

            if state == 'esc_inter':
                if '@' <= ch <= '~':
                    state = 'text'
                continue

            if state == 'csi':
                if ch == '\x1b':
                    # stray ESC resets state machine
                    state = 'esc'
                    continue
                if 0x40 <= code <= 0x7e:
                    state = 'text'
                continue

            if state == 'osc':
                if ch == '\x07' or ch == '\x9c':
                    state = 'text'
                elif ch == '\x1b':
                    state = 'osc_esc'
                continue

            if state == 'osc_esc':
                if ch in ('\\', '\x07', '\x9c'):
                    state = 'text'
                elif ch == '\x1b':
                    state = 'osc_esc'
                else:
                    state = 'osc'
                continue

            if state == 'string':
                if ch in ('\x07', '\x9c'):
                    state = 'text'
                elif ch == '\x1b':
                    state = 'string_esc'
                continue

            if state == 'string_esc':
                if ch in ('\\', '\x07', '\x9c'):
                    state = 'text'
                elif ch == '\x1b':
                    state = 'string_esc'
                else:
                    state = 'string'
                continue

        self.state = state
        return ''.join(result)


_ansi_cleaner = _AnsiCleaner()

# Get script directory for storing log files
script_dir = Path(__file__).parent.absolute()
log_file = script_dir / "logs" / f"bridge_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
os.makedirs(script_dir / "logs", exist_ok=True)

# Configure logging output to file
logging.basicConfig(
    level=logging.INFO,  # Can be changed to DEBUG to see details
    format="%(asctime)s [%(levelname)s]: %(message)s",
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
    def __init__(self, server_cmd=None, api_key=None, model=None, voice=None, mode=None):
        # Get the directory where this script is located
        script_dir = Path(__file__).parent.absolute()
        narrator_path = script_dir / "narrator-mcp" / "server.py"

        # Store configuration
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.mode = mode  # "chat" or "narration"
        self.config_sent = False

        # Use default command if not provided. Prefer the packaged server if present.
        custom_cmd = server_cmd is not None
        if not custom_cmd:
            if not narrator_path.exists():
                raise FileNotFoundError(
                    f"Could not locate narrator MCP server script at {narrator_path}. "
                    "Please run from the repo root or pass a custom server command."
                )
            # Use uv run to ensure correct Python environment with dependencies
            server_cmd = ["uv", "run", "python", str(narrator_path)]
        else:
            narrator_path = Path(server_cmd[-1]) if server_cmd else Path("<custom>")

        logger.info("🚀 Starting MCP Server subprocess...")
        logger.info(f"📁 Script directory: {script_dir}")
        if custom_cmd:
            logger.info(f"📄 Custom server command: {' '.join(server_cmd)}")
        else:
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
        self.config_event = threading.Event()
        self.config_response = None

        # Track pending requests to wait for responses
        self.pending_requests = {}  # id -> timestamp
        self.responses_received = {}  # id -> response

        # Statistics
        self.audio_chunks_received = 0
        self.text_tokens_received = 0

        # Audio player for streaming playback
        self.audio_player = AudioPlayer()
        self.audio_player.start()

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

        # Send config with API key if provided
        if self.api_key:
            self._send_config()

    def _send_config(self):
        """Send config with API key to MCP Server"""
        config_params = {"api_key": self.api_key}
        if self.model:
            config_params["model"] = self.model
        if self.voice:
            config_params["voice"] = self.voice
        if self.mode:
            config_params["mode"] = self.mode

        self._send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "config",
            "params": config_params
        })

        config_info = f"model={self.model or 'default'}, voice={self.voice or 'default'}, mode={self.mode or 'chat'}"
        logger.info(f"🔑 Sent config to MCP Server ({config_info})")

        # Wait for config response
        if self.config_event.wait(timeout=5.0):
            logger.info("✅ Config accepted by MCP Server")
            self.config_sent = True
        else:
            logger.error("❌ Timeout waiting for config response")

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
                    # Handle MCP protocol notifications
                    method = msg.get("method", "")
                    if method == "notifications/shutdown":
                        logger.info(f"🛑 Received shutdown notification from MCP Server: {msg.get('params', {})}")
                        continue

                    # Handle narration events (text_token, audio_chunk)
                    event_type = msg.get("event", "")
                    if event_type == "text_token":
                        token = msg.get("data", "")
                        self.text_tokens_received += 1
                        logger.debug(f"📝 Text token: {token}")
                        continue
                    elif event_type == "audio_chunk":
                        encoding = msg.get("encoding", "unknown")
                        data_hex = msg.get("data", "")
                        data_len = len(data_hex)
                        self.audio_chunks_received += 1
                        logger.info(f"🔊 Audio chunk #{self.audio_chunks_received} received ({encoding}, {data_len} chars)")

                        # Decode hex and play audio
                        try:
                            if encoding == "hex":
                                audio_bytes = bytes.fromhex(data_hex)
                                self.audio_player.add_chunk(audio_bytes)
                                logger.debug(f"   Added {len(audio_bytes)} bytes to playback queue")
                            else:
                                logger.warning(f"⚠️  Unsupported audio encoding: {encoding}")
                        except Exception as e:
                            logger.error(f"❌ Error decoding/playing audio: {e}")

                        continue

                    # Unknown notification/event
                    if not method and not event_type:
                        logger.debug(f"Unknown message (no id): {msg}")
                    continue

                # Check if it's an initialize response (id=0)
                if msg.get("id") == 0 and "result" in msg:
                    self.initialize_response = msg
                    self.initialize_event.set()
                    logger.info(f"✅ Received initialize response: {msg.get('result', {})}")

                # Check if it's a config response (id=1)
                if msg.get("id") == 1 and "result" in msg:
                    self.config_response = msg
                    self.config_event.set()
                    logger.info(f"✅ Received config response: {msg.get('result', {})}")

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
            line = line.strip()
            if line:
                # Log MCP server errors at INFO level so they're always visible
                logger.info(f"🔴 MCP Server Log: {line}")

    def send_chunk(self, text):
        """Send text chunks to MCP Server - use narrate method"""
        if not self.config_sent:
            logger.warning("⚠️ Config not sent yet, skipping narrate request")
            return

        req = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000),
            "method": "narrate",
            "params": {
                "prompt": text
            }
        }
        self.pending_requests[req["id"]] = time.time()
        self._send(req)
        logger.info(f"📤 Sent text chunk to MCP Server:\n{text}")

    def wait_for_responses(self, timeout=5.0):
        """Wait for all pending requests to receive responses"""
        start_time = time.time()
        last_count = len(self.pending_requests)

        logger.info(f"⏳ Waiting for {last_count} pending narration request(s)...")

        while self.pending_requests and (time.time() - start_time) < timeout:
            current_count = len(self.pending_requests)
            if current_count != last_count:
                logger.info(f"   {current_count} narration(s) still processing...")
                last_count = current_count
            time.sleep(0.5)

        if self.pending_requests:
            logger.warning(f"⚠️ Timeout: {len(self.pending_requests)} narrations did not complete in {timeout}s")
            logger.warning(f"   Pending request IDs: {list(self.pending_requests.keys())}")
        else:
            logger.info("✅ All narration requests completed")

    def cleanup(self):
        """Clean up MCP Server process and audio player"""
        logger.info("🧹 Starting cleanup...")

        # Wait for audio playback to complete
        queue_size = self.audio_player.get_queue_size()
        logger.info(f"📊 Audio queue size: {queue_size}")
        if queue_size > 0:
            logger.info(f"⏳ Waiting for {queue_size} audio chunks to finish playing...")
            self.audio_player.wait_for_completion(timeout=10.0)
        else:
            logger.info("✅ Audio queue is empty, no need to wait")

        # Stop audio player
        logger.info("🛑 Stopping audio player...")
        self.audio_player.stop()
        logger.info("✅ Audio player stopped")

        # Clean up MCP Server
        mcp_status = self.proc.poll()
        logger.info(f"📊 MCP Server process status: {mcp_status}")

        if mcp_status is None:
            logger.info("🛑 Terminating MCP Server process...")
            self.proc.terminate()

            # Give MCP Server some time to send shutdown notification
            import time
            time.sleep(0.2)

            try:
                self.proc.wait(timeout=4.8)  # Total 5 seconds, already waited 0.2 seconds
                logger.info("✅ MCP Server process terminated gracefully")
            except subprocess.TimeoutExpired:
                logger.warning("⚠️ MCP Server didn't terminate, forcing kill...")
                self.proc.kill()
                self.proc.wait()
                logger.info("✅ MCP Server process killed")
        else:
            logger.info(f"✅ MCP Server process already exited (code: {mcp_status})")

        logger.info("🧹 Cleanup complete")


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

    cleaned = _ansi_cleaner.clean(text)

    # Remove other common control characters (but keep newlines/tabs so transcripts stay readable)
    cleaned = re.sub(r'[\x00-\x07\x0b\x0c\x0e-\x1f\x7f]', '', cleaned)

    # Remove garbled characters (replacement character U+FFFD)
    cleaned = cleaned.replace('\ufffd', '')
    # Remove other invalid Unicode characters
    cleaned = re.sub(r'[\u200b-\u200f\u202a-\u202e\ufeff]', '', cleaned)

    return cleaned


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

    # cleaned = filter_ui_elements(cleaned)

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
    def __init__(self, min_window_seconds=2.0, pause_threshold=5.0):
        self.buffer = ""  # Accumulated text data
        self.window_start_time = None  # Current window start time
        self.last_data_time = None  # Time of last data arrival
        self.min_window_seconds = min_window_seconds  # Minimum accumulation time: 1 second
        self.pause_threshold = pause_threshold  # Pause threshold: 2 seconds
        self.force_flush_all = False  # When True, flush() will send entire buffer

    def _split_incomplete_escape_tail(self, text: str):
        """Return (safe_text, tail) ensuring we don't cut through ANSI sequences."""
        if not text:
            return text, ""

        tail_patterns = [
            # OSC without terminator
            '(\x1b][^\x07\x1b]*)$',
            # CSI (ESC[ or single-byte CSI) missing final command
            '((?:\x1b\[|\x9b)[0-9;:?<>]*[ -/]*)$',
            # ESC with intermediates only
            '(\x1b[\x20-\x2f]*)$',
            # Lone ESC
            '(\x1b)$',
        ]

        for pattern in tail_patterns:
            match = re.search(pattern, text)
            if match:
                start = match.start()
                return text[:start], text[start:]

        return text, ""

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

        # TEMPORARY: Allow flushing without newlines based on time windows
        # Set to False to restore original behavior (require newlines for min_window_seconds flush)
        ALLOW_FLUSH_WITHOUT_NEWLINES = True

        # Check if minimum time window is exceeded
        if self.window_start_time and \
           (current_time - self.window_start_time) >= self.min_window_seconds:
            if has_complete:
                self.force_flush_all = False
                return True
            # TEMPORARY: Also flush if no newlines but time window exceeded
            elif ALLOW_FLUSH_WITHOUT_NEWLINES and len(self.buffer) > 0:
                self.force_flush_all = True
                return True

        # Check if pause threshold is exceeded
        if self.last_data_time and \
           (current_time - self.last_data_time) >= self.pause_threshold:
            if has_complete:
                self.force_flush_all = False
                return True
            if len(self.buffer) > 0:
                # No newline yet, but we've been idle long enough—flush everything to avoid stale text
                self.force_flush_all = True
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

        if last_newline == -1 or self.force_flush_all:
            # Either no newline yet or we were explicitly told to flush the whole buffer
            result = self.buffer
            self.buffer = ""
            self.window_start_time = None
            self.last_data_time = None
            self.force_flush_all = False
        else:
            # Send complete lines up to the last newline
            result = self.buffer[:last_newline + 1]  # Include newline
            self.buffer = self.buffer[last_newline + 1:]  # Keep incomplete lines

            # If there's remaining data, update window start time (start counting from remaining data)
            if self.buffer:
                self.window_start_time = time.time()
            else:
                self.window_start_time = None
                self.last_data_time = None

        safe_text, tail = self._split_incomplete_escape_tail(result)
        if tail:
            # Prepend tail back to buffer so we flush it with the next chunk once complete
            self.buffer = tail + self.buffer
            if self.window_start_time is None:
                self.window_start_time = time.time()
            self.last_data_time = time.time()
            if not safe_text:
                return ""

        return safe_text

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


class StatusBar:
    """
    Simple status bar displayed at the bottom of the terminal
    Shows buffer status, pending requests, and statistics
    """
    def __init__(self):
        self.rows, self.cols = self._get_terminal_size()
        self.status_line = self.rows  # Use last line for status
        self.enabled = sys.stdout.isatty()  # Only enable if stdout is a TTY

    def _get_terminal_size(self):
        """Get current terminal size"""
        try:
            fallback = shutil.get_terminal_size(fallback=(80, 24))
            return fallback.lines, fallback.columns
        except:
            return 24, 80

    def update(self, buffer_size=0, pending_requests=0, audio_chunks=0, text_tokens=0):
        """Update status bar with current information"""
        if not self.enabled:
            return

        # Update terminal size in case it changed
        self.rows, self.cols = self._get_terminal_size()
        self.status_line = self.rows

        # Build status text with fixed-width fields to prevent flickering
        # Format: Narrator: Buffer: 1234 | Pending: 5 | Audio: 678 | Tokens: 9012
        status_text = (
            f"Narrator: "
            f"Buffer: {buffer_size:>6} | "
            f"Pending: {pending_requests:>3} | "
            f"Audio: {audio_chunks:>6} | "
            f"Tokens: {text_tokens:>6}"
        )

        # Ensure fixed width by padding or truncating to terminal width
        max_len = self.cols
        if len(status_text) > max_len:
            status_text = status_text[:max_len]
        else:
            # Pad with spaces to fill the line
            status_text = status_text.ljust(max_len)

        # Save cursor position, move to status line, update, restore cursor
        # Use bright colors: cyan background (46) + black text (30) + bold (1)
        try:
            sys.stdout.write('\x1b[s')  # Save cursor
            sys.stdout.write(f'\x1b[{self.status_line};1H')  # Move to status line
            sys.stdout.write('\x1b[K')  # Clear line
            # Bright cyan background (46) + bold black text (1;30) for high contrast
            sys.stdout.write('\x1b[46;1;30m' + status_text + '\x1b[0m')  # Bright cyan bg, bold black text
            sys.stdout.write('\x1b[u')  # Restore cursor
            sys.stdout.flush()
        except (OSError, IOError):
            # Terminal might not support these codes, silently fail
            pass

    def clear(self):
        """Clear the status bar"""
        if not self.enabled:
            return
        try:
            sys.stdout.write('\x1b[s')
            sys.stdout.write(f'\x1b[{self.status_line};1H')
            sys.stdout.write('\x1b[K')
            sys.stdout.write('\x1b[u')
            sys.stdout.flush()
        except (OSError, IOError):
            pass


if __name__ == "__main__":
    import pty
    import select
    import termios
    import tty
    import signal
    import argparse

    def _get_terminal_window_size():
        """Return the host terminal (rows, cols), falling back to 24x80."""
        if sys.stdin.isatty():
            try:
                packed = fcntl.ioctl(
                    sys.stdin.fileno(),
                    termios.TIOCGWINSZ,
                    struct.pack('HHHH', 0, 0, 0, 0)
                )
                rows, cols, _, _ = struct.unpack('HHHH', packed)
                if rows and cols:
                    return rows, cols
            except OSError as exc:
                logger.debug(f"Failed to query terminal size: {exc}")

        fallback = shutil.get_terminal_size(fallback=(80, 24))
        return fallback.lines, fallback.columns

    def _sync_pty_window_size(master_fd):
        """Propagate the host terminal window size to the PTY."""
        rows, cols = _get_terminal_window_size()
        winsize = struct.pack('HHHH', rows, cols, 0, 0)
        try:
            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
            logger.debug(f"Updated PTY window size to {cols}x{rows}")
        except OSError as exc:
            logger.debug(f"Failed to update PTY window size: {exc}")

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

    # Load environment variables from .env file
    script_dir = Path(__file__).parent.absolute()
    env_file = script_dir / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        logger.info(f"📄 Loaded environment from {env_file}")
    else:
        logger.warning(f"⚠️ No .env file found at {env_file}")

    # Get API configuration from environment
    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL")
    voice = os.getenv("OPENAI_VOICE")
    mode = os.getenv("MODE")  # "chat" or "narration"

    # Check if terminal debug logging is enabled
    debug_terminal = os.getenv("BRIDGE_DEBUG_TERMINAL", "").lower() in ("1", "true", "yes", "on")
    if debug_terminal:
        logger.info("🔍 Terminal debug logging ENABLED (set BRIDGE_DEBUG_TERMINAL=0 to disable)")

    if not api_key:
        logger.error("❌ OPENAI_API_KEY not found in environment")
        logger.error("Please create a .env file with your OpenAI API key")
        logger.error(f"Example: cp {script_dir}/.env.example {script_dir}/.env")
        sys.exit(1)

    logger.info("🧩 Starting MCP Bridge...")
    bridge = MCPBridge(api_key=api_key, model=model, voice=voice, mode=mode)
    time.sleep(0.5)

    # Create a pseudo terminal pair
    master_fd, slave_fd = pty.openpty()

    # Propagate the current terminal size to the PTY so interactive UIs render correctly
    _sync_pty_window_size(master_fd)

    # Get terminal name
    slave_name = os.ttyname(slave_fd)
    logger.info(f"📺 Created PTY: {slave_name}")

    # Save current terminal settings (only if stdin is a TTY)
    old_settings = None
    stdin_is_tty = sys.stdin.isatty()
    if stdin_is_tty:
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
        if stdin_is_tty:
            tty.setraw(sys.stdin.fileno())

        def restore_terminal():
            """Restore terminal settings"""
            if old_settings is not None:
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

        # Keep PTY size in sync with local terminal resizes
        if hasattr(signal, 'SIGWINCH'):
            def _handle_winch(sig, frame):
                _sync_pty_window_size(master_fd)

            signal.signal(signal.SIGWINCH, _handle_winch)

        # Initialize text buffer
        # Increased accumulation time to reduce send frequency and LLM/TTS calls
        # This helps reduce lag when agent output is complete
        text_buffer = TextBuffer(min_window_seconds=3.5, pause_threshold=5.0)

        # Initialize status bar
        status_bar = StatusBar()
        last_status_update = 0
        status_update_interval = 0.5  # Update status bar every 0.5 seconds

        # Bidirectional communication loop
        try:
            while True:
                current_time = time.time()

                # Update status bar periodically
                if current_time - last_status_update >= status_update_interval:
                    status_bar.update(
                        buffer_size=len(text_buffer.buffer),
                        pending_requests=len(bridge.pending_requests),
                        audio_chunks=bridge.audio_chunks_received,
                        text_tokens=bridge.text_tokens_received
                    )
                    last_status_update = current_time

                # Check if buffer should be flushed (even if there's no new data)
                if text_buffer.should_flush(current_time):
                    buffered_text = text_buffer.flush()
                    if buffered_text:
                        clean = clean_text(buffered_text)
                        if clean:
                            bridge.send_chunk(clean)
                            # Update status bar after sending
                            status_bar.update(
                                buffer_size=len(text_buffer.buffer),
                                pending_requests=len(bridge.pending_requests),
                                audio_chunks=bridge.audio_chunks_received,
                                text_tokens=bridge.text_tokens_received
                            )
                            last_status_update = current_time

                # Check which file descriptors have data to read
                fds_to_read = [master_fd]
                if stdin_is_tty:
                    fds_to_read.append(sys.stdin)
                ready, _, _ = select.select(fds_to_read, [], [], 0.1)

                # Read from command output (master_fd)
                if master_fd in ready:
                    try:
                        data = os.read(master_fd, 1024)
                        if not data:
                            break

                        # Debug logging: log raw terminal output
                        if debug_terminal:
                            try:
                                text = data.decode('utf-8', errors='replace')
                                has_newline = '\n' in text
                                has_cr = '\r' in text
                                newline_count = text.count('\n')
                                cr_count = text.count('\r')

                                newline_str = "\\n"
                                cr_str = "\\r"
                                logger.info(
                                    f"🔍 TERMINAL RAW: len={len(data)} bytes, "
                                    f"text_len={len(text)} chars, "
                                    f"has_{newline_str}={has_newline}, has_{cr_str}={has_cr}, "
                                    f"{newline_str}_count={newline_count}, {cr_str}_count={cr_count}\n"
                                    f"   Full content: {repr(text)}"
                                )
                            except Exception as e:
                                logger.warning(f"🔍 TERMINAL RAW: Failed to decode for logging: {e}")

                        # Output to terminal
                        sys.stdout.buffer.write(data)
                        sys.stdout.buffer.flush()

                        # Add to buffer (don't process immediately)
                        try:
                            text = data.decode('utf-8', errors='replace')
                            current_time = time.time()
                            text_buffer.add_data(text, current_time)

                            # Debug logging: log buffer state after adding data
                            if debug_terminal:
                                buffer_has_newline = '\n' in text_buffer.buffer
                                buffer_newline_count = text_buffer.buffer.count('\n')
                                newline_str = "\\n"
                                logger.info(
                                    f"🔍 BUFFER STATE: total_len={len(text_buffer.buffer)}, "
                                    f"has_{newline_str}={buffer_has_newline}, {newline_str}_count={buffer_newline_count}, "
                                    f"window_start={text_buffer.window_start_time}, "
                                    f"last_data={text_buffer.last_data_time}"
                                )

                            # Check if should flush
                            if text_buffer.should_flush(current_time):
                                buffered_text = text_buffer.flush()
                                if buffered_text:
                                    clean = clean_text(buffered_text)
                                    if debug_terminal:
                                        logger.info(
                                            f"🔍 FLUSHED: buffered_len={len(buffered_text)}, "
                                            f"cleaned_len={len(clean) if clean else 0}, "
                                            f"will_send={bool(clean)}\n"
                                            f"   Flushed text: {repr(buffered_text)}"
                                        )
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

                            # Debug logging for remaining data
                            if debug_terminal:
                                try:
                                    text = data.decode('utf-8', errors='replace')
                                    has_newline_remaining = '\n' in text
                                    newline_str = "\\n"
                                    logger.info(
                                        f"🔍 TERMINAL REMAINING: len={len(data)} bytes, "
                                        f"text_len={len(text)}, has_{newline_str}={has_newline_remaining}\n"
                                        f"   Full content: {repr(text)}"
                                    )
                                except Exception as e:
                                    logger.warning(f"🔍 TERMINAL REMAINING: Failed to decode: {e}")

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
                    if debug_terminal:
                        logger.info(
                            f"🔍 FINAL FLUSH: buffered_len={len(buffered_text) if buffered_text else 0}\n"
                            f"   Content: {repr(buffered_text) if buffered_text else 'None'}"
                        )
                    if buffered_text:
                        clean = clean_text(buffered_text)
                        if debug_terminal:
                            logger.info(
                                f"🔍 FINAL CLEANED: cleaned_len={len(clean) if clean else 0}, "
                                f"will_send={bool(clean)}"
                            )
                        if clean:
                            bridge.send_chunk(clean)
                    break

        except KeyboardInterrupt:
            logger.info("⚠️ Interrupted by user")
        finally:
            # Clear status bar before restoring terminal
            if 'status_bar' in locals():
                status_bar.clear()
            restore_terminal()

            # Process final remaining buffer
            if text_buffer.has_data():
                buffered_text = text_buffer.flush_all()
                if debug_terminal:
                    logger.info(
                        f"🔍 FINALLY FLUSH: buffered_len={len(buffered_text) if buffered_text else 0}\n"
                        f"   Content: {repr(buffered_text) if buffered_text else 'None'}"
                    )
                if buffered_text:
                    clean = clean_text(buffered_text)
                    if debug_terminal:
                        logger.info(
                            f"🔍 FINALLY CLEANED: cleaned_len={len(clean) if clean else 0}, "
                            f"will_send={bool(clean)}"
                        )
                    if clean:
                        bridge.send_chunk(clean)

    finally:
        logger.info("🔚 Entering finally block - closing PTY and waiting for child process...")
        os.close(master_fd)
        logger.info("✅ PTY master fd closed")

        if cmd_proc.poll() is None:
            logger.info("⚠️ Child process still running, terminating...")
            cmd_proc.terminate()
        else:
            logger.info(f"✅ Child process already exited with code: {cmd_proc.poll()}")

        cmd_proc.wait()
        logger.info(f"✅ Child process wait() complete, exit code: {cmd_proc.returncode}")

        # Wait for narration to complete
        logger.info("⏳ Waiting for narration to complete...")
        if bridge.pending_requests:
            logger.info(f"   Waiting for {len(bridge.pending_requests)} pending narration requests...")

        # Wait up to 30 seconds for all audio to be generated and sent
        bridge.wait_for_responses(timeout=30.0)

        if bridge.pending_requests:
            logger.warning(f"⚠️  Some narrations may not have completed: {len(bridge.pending_requests)} pending")
        else:
            logger.info("✅ All narrations completed")

        # Show statistics
        logger.info(f"📊 Session statistics:")
        logger.info(f"   Text tokens: {bridge.text_tokens_received}")
        logger.info(f"   Audio chunks: {bridge.audio_chunks_received}")

        # Clean up MCP Server
        logger.info("🧹 Calling bridge.cleanup()...")
        bridge.cleanup()
        logger.info("✅ Bridge shutdown complete")
