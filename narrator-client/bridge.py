# bridge.py
import asyncio
import base64
import json
import fcntl
import logging
import os
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import termios
import time
import tty
import unicodedata
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv
import httpx
from fastmcp import Client

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
client_dir = Path(__file__).parent.absolute()
log_file = client_dir / "logs" / f"bridge_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
os.makedirs(client_dir / "logs", exist_ok=True)

# Configure logging: file for all logs, console only for errors
file_handler = RotatingFileHandler(
    log_file,
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)

# Console handler only for errors
console_handler = logging.StreamHandler(sys.stderr)
console_handler.setLevel(logging.ERROR)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s]: %(message)s",
    handlers=[file_handler, console_handler]
)
logger = logging.getLogger(__name__)
logger.info(f"📝 Logging to file: {log_file}")


class MCPBridge:
    """MCP client bridge using FastMCP with streamable-http or stdio transport."""

    def __init__(self, api_key=None, model=None, voice=None, mode=None,
                 character=None, base_url=None, default_headers=None, tts_api_key=None,
                 use_stdio=False):
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.mode = mode
        self.character = character
        self.base_url = base_url
        self.default_headers = default_headers
        self.tts_api_key = tts_api_key
        self.use_stdio = use_stdio  # New parameter

        # Will be initialized in async context
        self.client: Client | None = None
        self.server_process: subprocess.Popen | None = None
        self.server_url = "http://localhost:8000/mcp"
        self.audio_player = AudioPlayer()

        # Statistics
        self.narrations_sent = 0
        self.narrations_completed = 0

    async def __aenter__(self):
        """Initialize MCP client connection."""
        # Get project root (parent of narrator-client)
        client_dir = Path(__file__).parent.absolute()
        project_root = client_dir.parent
        narrator_path = project_root / "narrator-mcp" / "server.py"

        if not narrator_path.exists():
            raise FileNotFoundError(
                f"Could not locate narrator MCP server script at {narrator_path}"
            )

        logger.info("🚀 Starting MCP client...")
        logger.info(f"📁 Client directory: {client_dir}")
        logger.info(f"📁 Project root: {project_root}")
        logger.info(f"📄 Narrator path: {narrator_path}")

        narrator_dir = narrator_path.parent

        if self.use_stdio:
            # Local stdio mode
            logger.info("🔌 Using stdio transport (local mode)")
            config = {
                "mcpServers": {
                    "narrator-mcp": {
                        "command": "uv",
                        "args": ["run", "python", "server.py"],
                        "cwd": str(narrator_dir),
                        "env": {"MCP_TRANSPORT": "stdio"}
                    }
                }
            }
            # In stdio mode, no need to start HTTP server, FastMCP client will manage subprocess automatically
        else:
            # Remote streamable-http mode
            logger.info("🌐 Using streamable-http transport (remote mode)")
            # Check if server is already running
            server_running = await self._check_server_running()

            if not server_running:
                logger.info("🔧 MCP server not running, starting it...")
                await self._start_server(project_root, narrator_path)
            else:
                logger.info("✅ MCP server already running")

            config = {
                "mcpServers": {
                    "narrator-mcp": {
                        "url": self.server_url,
                        "transport": "streamable-http"
                    }
                }
            }

        logger.info("🤝 Connecting to MCP server...")
        self.client = Client(config)
        await self.client.__aenter__()
        logger.info("✅ MCP client connected")

        # Configure server via tool call
        await self._send_config()

        # Start audio player
        self.audio_player.start()
        logger.info("🔊 Audio player started")

        return self

    async def _check_server_running(self) -> bool:
        """Check if MCP server is running by attempting HTTP connection."""
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                # Try to connect to the server endpoint
                response = await client.get(self.server_url)
                return response.status_code < 500  # Any non-server-error means server is up
        except (httpx.ConnectError, httpx.TimeoutException):
            return False
        except Exception as e:
            logger.debug(f"Server check error: {e}")
            return False

    def _log_server_output(self):
        """Read and log server stdout/stderr output."""
        if not self.server_process:
            return

        try:
            # Read remaining output after process has terminated
            # Use communicate with timeout to avoid blocking
            try:
                stdout_data, stderr_data = self.server_process.communicate(timeout=1.0)
            except subprocess.TimeoutExpired:
                # If still running, try to read what's available
                logger.debug("Server process still has output, reading available data...")
                return

            if stdout_data:
                stdout_text = stdout_data.decode('utf-8', errors='replace').strip()
                if stdout_text:
                    logger.info(f"📄 MCP Server stdout:\n{stdout_text}")

            if stderr_data:
                stderr_text = stderr_data.decode('utf-8', errors='replace').strip()
                if stderr_text:
                    logger.info(f"📄 MCP Server stderr:\n{stderr_text}")
        except Exception as e:
            logger.debug(f"Could not read server output: {e}")

    async def _start_server(self, project_root: Path, narrator_path: Path):
        """Start MCP server as subprocess."""
        logger.info(f"🚀 Starting MCP server: {narrator_path}")
        # Run from narrator-mcp directory so it uses its own pyproject.toml
        narrator_dir = narrator_path.parent
        self.server_process = subprocess.Popen(
            ["uv", "run", "python", "server.py"],
            cwd=str(narrator_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ.copy()
        )

        # Wait for server to start (poll HTTP endpoint)
        max_attempts = 30
        for attempt in range(max_attempts):
            await asyncio.sleep(0.5)
            if await self._check_server_running():
                logger.info(f"✅ MCP server started successfully (attempt {attempt + 1})")
                return

            # Check if process died
            if self.server_process.poll() is not None:
                stdout, stderr = self.server_process.communicate()
                error_msg = f"MCP server process exited with code {self.server_process.returncode}"
                if stderr:
                    error_msg += f"\nStderr: {stderr.decode('utf-8', errors='replace')}"
                if stdout:
                    error_msg += f"\nStdout: {stdout.decode('utf-8', errors='replace')}"
                raise RuntimeError(error_msg)

        raise RuntimeError(f"MCP server failed to start after {max_attempts} attempts")

    async def __aexit__(self, *args):
        """Cleanup MCP client."""
        logger.info("🧹 Starting cleanup...")

        # Wait for audio playback to complete
        queue_size = self.audio_player.get_queue_size()
        if queue_size > 0:
            logger.info(f"⏳ Waiting for {queue_size} audio chunks to finish playing...")
            self.audio_player.wait_for_completion(timeout=10.0)

        # Stop audio player
        logger.info("🛑 Stopping audio player...")
        self.audio_player.stop()

        # Close MCP client
        if self.client:
            logger.info("🔌 Closing MCP client...")
            await self.client.__aexit__(*args)

        # Terminate server process if we started it (only for HTTP mode)
        if not self.use_stdio and self.server_process:
            logger.info("🛑 Terminating MCP server process...")
            try:
                self.server_process.terminate()
                # Wait up to 5 seconds for graceful shutdown
                try:
                    self.server_process.wait(timeout=5.0)
                    # Read and log server output after termination
                    self._log_server_output()
                    logger.info(f"✅ MCP server terminated (exit code: {self.server_process.returncode})")
                except subprocess.TimeoutExpired:
                    logger.warning("⚠️ MCP server did not terminate gracefully, forcing kill...")
                    self.server_process.kill()
                    self.server_process.wait()
                    # Read and log server output after kill
                    self._log_server_output()
                    logger.info("✅ MCP server killed")
            except Exception as e:
                logger.error(f"❌ Error terminating server process: {e}")
                # Try to read output even if there was an error
                try:
                    self._log_server_output()
                except:
                    pass

        # Show statistics
        logger.info(f"📊 Session statistics:")
        logger.info(f"   Narrations sent: {self.narrations_sent}")
        logger.info(f"   Narrations completed: {self.narrations_completed}")

        logger.info("✅ Bridge shutdown complete")

    async def _send_config(self):
        """Configure server via tool call."""
        config_args = {"llm_api_key": self.api_key}
        if self.model:
            config_args["llm_model"] = self.model
        if self.voice:
            config_args["voice"] = self.voice
        if self.mode:
            config_args["mode"] = self.mode
        if self.character:
            config_args["character"] = self.character
        if self.base_url:
            config_args["base_url"] = self.base_url
        if self.default_headers:
            config_args["default_headers"] = self.default_headers
        if self.tts_api_key:
            config_args["tts_api_key"] = self.tts_api_key

        provider_info = f"base_url={self.base_url}" if self.base_url else "provider=OpenAI"
        config_info = (
            f"model={self.model or 'default'}, voice={self.voice or 'default'}, "
            f"mode={self.mode or 'chat'}, character={self.character or 'default'}, {provider_info}"
        )

        logger.info(f"🔑 Configuring server ({config_info})...")
        result = await self.client.call_tool("configure", config_args)
        # FastMCP returns CallToolResult object with data attribute
        if hasattr(result, 'data'):
            logger.info(f"✅ Configuration: {result.data}")
        elif isinstance(result, str):
            logger.info(f"✅ Configuration: {result}")
        else:
            logger.info(f"✅ Configuration: {result}")

    async def send_chunk(self, text: str):
        """Send text chunk for narration via MCP tool call."""
        if not self.client:
            logger.warning("⚠️ Client not initialized, skipping narrate request")
            return

        self.narrations_sent += 1
        logger.info(f"📤 Sending narration request #{self.narrations_sent}:\n{text}")

        try:
            # Call narrate tool
            result = await self.client.call_tool("narrate", {"prompt": text})

            # FastMCP returns CallToolResult object with data attribute
            if hasattr(result, 'data'):
                # Use data attribute which contains the string result
                result_str = result.data
            elif isinstance(result, str):
                result_str = result
            else:
                # Fallback: try to get from content
                if hasattr(result, 'content') and result.content:
                    result_str = result.content[0].text if hasattr(result.content[0], 'text') else str(result.content[0])
                else:
                    result_str = str(result)

            # Parse JSON result
            response_data = json.loads(result_str)

            generated_text = response_data.get("text", "")
            audio_base64 = response_data.get("audio", "")
            audio_format = response_data.get("format", "mp3")

            # Decode and play audio (only if audio data exists and is not empty)
            audio_bytes = b''
            if audio_base64:
                try:
                    audio_bytes = base64.b64decode(audio_base64)
                except Exception as e:
                    logger.warning(f"⚠️ Failed to decode audio base64: {e}")
                    audio_bytes = b''

            if len(audio_bytes) > 0:
                self.audio_player.add_chunk(audio_bytes)
                self.narrations_completed += 1
                logger.info(
                    f"✅ Narration #{self.narrations_completed} complete: "
                    f"{len(generated_text)} chars, {len(audio_bytes)} bytes {audio_format}"
                )
            else:
                # No audio generated (e.g., LLM returned empty string)
                self.narrations_completed += 1
                logger.info(
                    f"✅ Narration #{self.narrations_completed} complete: "
                    f"{len(generated_text)} chars, 0 bytes {audio_format} (no audio generated)"
                )

        except Exception as e:
            logger.error(f"❌ Narration failed: {e}", exc_info=True)
            raise


def clean_ansi_codes(text: str) -> str:
    """
    Clean ANSI escape sequences, restore plain text.
    """
    if not text:
        return text

    cleaned = _ansi_cleaner.clean(text)

    # Remove other common control characters (but keep newlines/tabs)
    cleaned = re.sub(r'[\x00-\x07\x0b\x0c\x0e-\x1f\x7f]', '', cleaned)

    # Remove garbled characters
    cleaned = cleaned.replace('\ufffd', '')
    cleaned = re.sub(r'[\u200b-\u200f\u202a-\u202e\ufeff]', '', cleaned)

    return cleaned


def filter_ui_elements(text: str) -> str:
    """
    Keep only natural language characters, filter out special characters, icons, UI elements, etc.
    """
    if not text:
        return ""

    lines = text.split('\n')
    filtered_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Filter empty user input
        if line.startswith('>'):
            content_after_arrow = line[1:].strip()
            if not content_after_arrow:
                continue

        # Filter Claude Code prompts
        if line.startswith('?'):
            continue

        # Filter remaining OSC sequences
        if re.match(r'^\]\d+;', line.strip()):
            continue

        # Filter UI prompt text
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

        # Filter separator lines
        if len(line) > 20:
            line_chars = set(line.replace(' ', ''))
            separator_chars = set('-=─━')
            if line_chars.issubset(separator_chars) or \
               (len(line_chars & separator_chars) > 0 and len(line_chars - separator_chars) <= 2):
                continue

        # Keep only natural language characters
        filtered_chars = []
        for char in line:
            cat = unicodedata.category(char)

            if cat.startswith('L'):  # Letters
                filtered_chars.append(char)
            elif cat.startswith('N'):  # Numbers
                filtered_chars.append(char)
            elif cat == 'Zs':  # Space
                filtered_chars.append(char)
            elif char == '|':
                filtered_chars.append(char)
            elif cat.startswith('P'):  # Punctuation
                if char in '.,!?;:\'"()[]{}-_/\\@#$%&*+=<>|~`^…—–«»„"':
                    filtered_chars.append(char)
                elif '\u3000' <= char <= '\u303f' or '\uff00' <= char <= '\uffef':
                    filtered_chars.append(char)
            elif char in '-=─━>':
                filtered_chars.append(char)

        line = ''.join(filtered_chars)

        # Clean excessive whitespace
        line = re.sub(r'\s+', ' ', line).strip()

        if line:
            filtered_lines.append(line)

    return '\n'.join(filtered_lines)


def clean_text(text: str) -> str:
    """
    Clean Claude Code output, remove ANSI escape sequences and excessive whitespace.
    """
    if not text:
        return ""

    # First clean ANSI escape sequences
    cleaned = clean_ansi_codes(text)

    # Remove leading/trailing whitespace
    cleaned = cleaned.strip()

    return cleaned


class TextBuffer:
    """
    Text buffer that accumulates data and records timestamps to determine when to send.
    """

    def __init__(self, min_window_seconds=2.0, pause_threshold=5.0):
        self.buffer = ""
        self.window_start_time = None
        self.last_data_time = None
        self.min_window_seconds = min_window_seconds
        self.pause_threshold = pause_threshold
        self.force_flush_all = False

    def _split_incomplete_escape_tail(self, text: str):
        """Return (safe_text, tail) ensuring we don't cut through ANSI sequences."""
        if not text:
            return text, ""

        tail_patterns = [
            '(\x1b][^\x07\x1b]*)$',
            '((?:\x1b\[|\x9b)[0-9;:?<>]*[ -/]*)$',
            '(\x1b[\x20-\x2f]*)$',
            '(\x1b)$',
        ]

        for pattern in tail_patterns:
            match = re.search(pattern, text)
            if match:
                start = match.start()
                return text[:start], text[start:]

        return text, ""

    def add_data(self, text: str, current_time: float):
        """Add new data to buffer."""
        self.buffer += text
        if self.window_start_time is None:
            self.window_start_time = current_time
        self.last_data_time = current_time

    def has_complete_lines(self) -> bool:
        """Check if buffer has complete lines."""
        return self.buffer and '\n' in self.buffer

    def should_flush(self, current_time: float) -> bool:
        """Determine if buffer should be flushed."""
        if not self.buffer:
            return False

        has_complete = self.has_complete_lines()
        ALLOW_FLUSH_WITHOUT_NEWLINES = True

        # Check if minimum time window is exceeded
        if self.window_start_time and \
           (current_time - self.window_start_time) >= self.min_window_seconds:
            if has_complete:
                self.force_flush_all = False
                return True
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
                self.force_flush_all = True
                return True

        return False

    def flush(self) -> str:
        """Flush buffer, return complete lines."""
        if not self.buffer:
            return ""

        last_newline = self.buffer.rfind('\n')

        if last_newline == -1 or self.force_flush_all:
            result = self.buffer
            self.buffer = ""
            self.window_start_time = None
            self.last_data_time = None
            self.force_flush_all = False
        else:
            result = self.buffer[:last_newline + 1]
            self.buffer = self.buffer[last_newline + 1:]

            if self.buffer:
                self.window_start_time = time.time()
            else:
                self.window_start_time = None
                self.last_data_time = None

        safe_text, tail = self._split_incomplete_escape_tail(result)
        if tail:
            self.buffer = tail + self.buffer
            if self.window_start_time is None:
                self.window_start_time = time.time()
            self.last_data_time = time.time()
            if not safe_text:
                return ""

        return safe_text

    def has_data(self) -> bool:
        """Check if buffer has data."""
        return bool(self.buffer)

    def flush_all(self) -> str:
        """Force flush all buffer contents."""
        if not self.buffer:
            return ""

        result = self.buffer
        self.buffer = ""
        self.window_start_time = None
        self.last_data_time = None
        return result


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


async def run_pty_with_narration(bridge: MCPBridge, cmd: list[str]):
    """Run command in PTY with narration."""
    # Create PTY
    master_fd, slave_fd = pty.openpty()
    _sync_pty_window_size(master_fd)

    slave_name = os.ttyname(slave_fd)
    logger.info(f"📺 Created PTY: {slave_name}")

    # Save current terminal settings
    old_settings = None
    stdin_is_tty = sys.stdin.isatty()
    if stdin_is_tty:
        old_settings = termios.tcgetattr(sys.stdin)

    logger.info(f"🚀 Running command in PTY: {' '.join(cmd)}")

    # Start command in PTY
    cmd_proc = subprocess.Popen(
        cmd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        start_new_session=True
    )

    os.close(slave_fd)

    # Define restore_terminal BEFORE setting raw mode, so it's always available
    def restore_terminal():
        """Restore terminal settings."""
        if old_settings is not None and stdin_is_tty:
            try:
                # Use TCSAFLUSH to discard any pending input before restoring
                termios.tcsetattr(sys.stdin, termios.TCSAFLUSH, old_settings)
            except (OSError, termios.error) as e:
                logger.warning(f"Failed to restore terminal settings (TCSAFLUSH): {e}")
                # Try TCSADRAIN as fallback
                try:
                    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
                except (OSError, termios.error) as e2:
                    logger.warning(f"Failed to restore terminal settings (TCSADRAIN): {e2}")

    # Set terminal to raw mode
    try:
        if stdin_is_tty:
            tty.setraw(sys.stdin.fileno())

        def signal_handler(sig, frame):
            restore_terminal()
            os.close(master_fd)
            if cmd_proc.poll() is None:
                cmd_proc.terminate()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Keep PTY size in sync
        if hasattr(signal, 'SIGWINCH'):
            def _handle_winch(sig, frame):
                _sync_pty_window_size(master_fd)

            signal.signal(signal.SIGWINCH, _handle_winch)

        # Text buffer
        text_buffer = TextBuffer(min_window_seconds=3.5, pause_threshold=5.0)

        # Get event loop for async executor
        loop = asyncio.get_event_loop()

        # Async I/O loop
        try:
            while True:
                current_time = time.time()

                # Check if buffer should be flushed
                if text_buffer.should_flush(current_time):
                    buffered_text = text_buffer.flush()
                    if buffered_text:
                        clean = clean_text(buffered_text)
                        if clean:
                            await bridge.send_chunk(clean)

                # Non-blocking select
                fds_to_read = [master_fd]
                if stdin_is_tty:
                    fds_to_read.append(sys.stdin)
                ready, _, _ = select.select(fds_to_read, [], [], 0.1)

                # Read from PTY
                if master_fd in ready:
                    data = await loop.run_in_executor(None, os.read, master_fd, 1024)
                    if not data:
                        break

                    # Display to terminal
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()

                    # Buffer for narration
                    text = data.decode('utf-8', errors='replace')
                    text_buffer.add_data(text, current_time)

                # Forward user input
                if stdin_is_tty and sys.stdin in ready:
                    data = await loop.run_in_executor(None, os.read, sys.stdin.fileno(), 1024)
                    if not data:
                        break
                    await loop.run_in_executor(None, os.write, master_fd, data)

                # Check if command finished
                if cmd_proc.poll() is not None:
                    # Read remaining data
                    while True:
                        ready, _, _ = select.select([master_fd], [], [], 0.1)
                        if not ready:
                            break
                        try:
                            data = await loop.run_in_executor(None, os.read, master_fd, 1024)
                            if not data:
                                break

                            sys.stdout.buffer.write(data)
                            sys.stdout.buffer.flush()

                            text = data.decode('utf-8', errors='replace')
                            text_buffer.add_data(text, current_time)
                        except OSError:
                            break

                    # Flush remaining buffer
                    remaining = text_buffer.flush_all()
                    if remaining:
                        clean = clean_text(remaining)
                        if clean:
                            await bridge.send_chunk(clean)
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
                        await bridge.send_chunk(clean)

    finally:
        # Ensure terminal is restored even if inner try block fails
        restore_terminal()
        logger.info("🔚 Closing PTY...")
        os.close(master_fd)

        if cmd_proc.poll() is None:
            logger.info("⚠️ Terminating command process...")
            cmd_proc.terminate()

        cmd_proc.wait()
        logger.info(f"✅ Command process exited with code: {cmd_proc.returncode}")


async def async_main(cmd: list[str], api_key: str, model: str | None, voice: str | None,
                     mode: str | None, character: str | None, base_url: str | None,
                     default_headers: dict | None, tts_api_key: str | None,
                     use_stdio: bool = False):
    """Async main function."""
    async with MCPBridge(
        api_key=api_key,
        model=model,
        voice=voice,
        mode=mode,
        character=character,
        base_url=base_url,
        default_headers=default_headers,
        tts_api_key=tts_api_key,
        use_stdio=use_stdio
    ) as bridge:
        await run_pty_with_narration(bridge, cmd)


if __name__ == "__main__":
    import argparse

    # Switch to original working directory if set
    # This ensures commands run in the directory where user invoked the script
    original_cwd = os.environ.get('ORIGINAL_CWD')
    if original_cwd and os.path.isdir(original_cwd):
        os.chdir(original_cwd)
        logger.info(f"📁 Changed to original working directory: {original_cwd}")
    else:
        logger.info(f"📁 Using current working directory: {os.getcwd()}")

    parser = argparse.ArgumentParser(
        description='MCP Bridge - Run command in PTY and forward output to MCP server',
        epilog='''
Examples:
  python bridge.py claude
  python bridge.py python -i
  python bridge.py bash
  python bridge.py --use-stdio claude  # Use stdio transport for local mode
        '''
    )
    parser.add_argument('command', nargs=argparse.REMAINDER,
                       help='Command to run in PTY (e.g., claude, python -i, bash)')
    parser.add_argument('--use-stdio', action='store_true',
                       help='Use stdio transport for local MCP server (default: streamable-http for remote)')
    args = parser.parse_args()

    if not args.command:
        parser.error("command is required")

    # Load environment variables (look in client directory first, then project root)
    client_dir = Path(__file__).parent.absolute()
    project_root = client_dir.parent

    # Try client directory first
    env_file = client_dir / ".env"
    if not env_file.exists():
        # Fall back to project root
        env_file = project_root / ".env"

    if env_file.exists():
        load_dotenv(env_file)
        logger.info(f"📄 Loaded environment from {env_file}")
    else:
        logger.warning(f"⚠️ No .env file found at {client_dir / '.env'} or {project_root / '.env'}")

    # Get API configuration
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    openai_tts_api_key = os.getenv("OPENAI_TTS_API_KEY")

    base_url = None
    default_headers = None
    api_key = None
    tts_api_key = None

    # TTS API key: prefer OPENAI_TTS_API_KEY, fallback to OPENAI_API_KEY
    if openai_tts_api_key:
        tts_api_key = openai_tts_api_key
        logger.info("🔊 Using OPENAI_TTS_API_KEY for TTS")
    elif openai_api_key:
        tts_api_key = openai_api_key
        logger.info("🔊 Using OPENAI_API_KEY for TTS")
    else:
        logger.error("❌ TTS requires OpenAI API key")
        logger.error("Please set either OPENAI_TTS_API_KEY or OPENAI_API_KEY in .env file")
        sys.exit(1)

    if openrouter_api_key:
        # Use OpenRouter
        api_key = openrouter_api_key
        base_url = "https://openrouter.ai/api/v1"
        default_headers = {
            "HTTP-Referer": os.getenv("OPENROUTER_REFERER", "https://github.com/herrkaefer/vibe-narrator"),
            "X-Title": os.getenv("OPENROUTER_TITLE", "Vibe Narrator"),
        }
        logger.info("🌐 Using OpenRouter as LLM provider")
    elif openai_api_key:
        # Use OpenAI
        api_key = openai_api_key
        custom_base_url = os.getenv("OPENAI_BASE_URL")
        if custom_base_url:
            base_url = custom_base_url
            logger.info(f"🔗 Using custom base URL: {base_url}")
        else:
            logger.info("🤖 Using OpenAI as LLM provider")
    else:
        logger.error("❌ Neither OPENAI_API_KEY nor OPENROUTER_API_KEY found in environment")
        logger.error("Please create a .env file with your API key")
        sys.exit(1)

    # Model configuration
    model = os.getenv("LLM_MODEL")
    voice = os.getenv("OPENAI_TTS_VOICE")
    mode = os.getenv("MODE")
    character = os.getenv("CHARACTER")

    logger.info("🧩 Starting MCP Bridge...")

    # Run async main
    asyncio.run(async_main(
        cmd=args.command,
        api_key=api_key,
        model=model,
        voice=voice,
        mode=mode,
        character=character,
        base_url=base_url,
        default_headers=default_headers,
        tts_api_key=tts_api_key,
        use_stdio=args.use_stdio
    ))

    logger.info("✅ Bridge session complete")
