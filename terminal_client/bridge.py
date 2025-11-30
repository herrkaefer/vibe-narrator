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
from typing import Any
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv
import httpx
from fastmcp import Client
from fastmcp.exceptions import ToolError

from audio_player import AudioPlayer

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pydub")

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
    """MCP client bridge using FastMCP with automatic transport selection.

    Transport is automatically determined based on NARRATOR_REMOTE_MCP_URL:
    - Not set: stdio (local mode, FastMCP manages subprocess)
    - localhost URL: streamable-http (connect to local HTTP server)
    - Remote URL: sse (connect to remote server)
    """

    def __init__(self, api_key=None, model=None, voice=None, mode=None,
                 character=None, base_url=None, default_headers=None, tts_api_key=None,
                 tts_provider=None):
        self.api_key = api_key
        self.model = model
        self.voice = voice
        self.mode = mode
        self.character = character
        self.base_url = base_url
        self.default_headers = default_headers
        self.tts_api_key = tts_api_key
        self.tts_provider = tts_provider

        # Optional MCP endpoint URL. Transport is auto-detected based on URL.
        self.mcp_url = os.getenv("NARRATOR_REMOTE_MCP_URL")

        # Logical-to-actual MCP tool name mapping (populated after connect)
        self.tool_names: dict[str, str] = {}

        # Will be initialized in async context
        self.client: Client | None = None
        self.server_process: subprocess.Popen | None = None
        self.audio_player = AudioPlayer()

        # Statistics
        self.narrations_sent = 0
        self.narrations_completed = 0

    def _is_local_url(self, url: str) -> bool:
        """Check if URL points to localhost."""
        if not url:
            return False
        url_lower = url.lower()
        return any(host in url_lower for host in [
            "localhost", "127.0.0.1", "0.0.0.0", "[::1]"
        ])

    async def __aenter__(self):
        """Initialize MCP client connection.

        Transport is automatically determined:
        - No URL configured: stdio (local mode, FastMCP manages subprocess)
        - localhost URL: streamable-http (connect to local HTTP server)
        - Remote URL: sse (connect to remote server)
        """
        # Get project root (parent of narrator-client)
        client_dir = Path(__file__).parent.absolute()
        project_root = client_dir.parent
        narrator_path = project_root / "narrator_mcp" / "server.py"

        if not self.mcp_url:
            # No URL configured: use stdio (local mode)
            if not narrator_path.exists():
                raise FileNotFoundError(
                    f"Could not locate narrator MCP server script at {narrator_path}"
                )

            logger.info("🚀 Starting MCP client in LOCAL STDIO mode...")
            logger.info(f"📁 Client directory: {client_dir}")
            logger.info(f"📁 Project root: {project_root}")
            logger.info(f"📄 Narrator path: {narrator_path}")

            narrator_dir = narrator_path.parent
            config = {
                "mcpServers": {
                    "narrator-mcp": {
                        "command": "uv",
                        "args": ["run", "python", "server.py"],
                        "cwd": str(narrator_dir),
                        "env": {"MCP_TRANSPORT": "stdio"},
                    }
                }
            }
            # In stdio mode, FastMCP client manages subprocess automatically

        elif self._is_local_url(self.mcp_url):
            # localhost URL: use streamable-http
            logger.info("🚀 Starting MCP client in LOCAL HTTP mode...")
            logger.info(f"🌐 Local MCP URL: {self.mcp_url}")

            # Check if server is already running
            server_running = await self._check_server_running(self.mcp_url)

            if not server_running:
                logger.info("🔧 MCP server not running, starting it...")
                await self._start_server(project_root, narrator_path, self.mcp_url)
            else:
                logger.info("✅ MCP server already running")

            config = {
                "mcpServers": {
                    "narrator-mcp": {
                        "url": self.mcp_url,
                        "transport": "streamable-http",
                    }
                }
            }

        else:
            # Remote URL: use sse
            logger.info("🚀 Starting MCP client in REMOTE SSE mode...")
            logger.info(f"🌐 Remote MCP URL: {self.mcp_url}")
            config = {
                "mcpServers": {
                    "narrator-mcp": {
                        "url": self.mcp_url,
                        "transport": "sse",
                    }
                }
            }

        logger.info("🤝 Connecting to MCP server...")
        self.client = Client(config)
        await self.client.__aenter__()
        logger.info("✅ MCP client connected")

        # Initialize tool name mappings based on available tools
        await self._init_tool_names()

        # Configure server via tool call
        await self._send_config()

        # Start audio player
        self.audio_player.start()
        logger.info("🔊 Audio player started")

        return self

    async def _init_tool_names(self):
        """Build mapping from logical tool names to actual MCP tool names.

        This allows the bridge to work with both local tools (e.g. \"narrate_text\")
        and remotely-prefixed tools (e.g. \"vibe_narrator_narrate_text\").

        Expected logical tool names:
        - configure
        - narrate_text
        - list_characters
        - get_config_status
        """
        if not self.client:
            logger.warning("⚠️ MCP client not initialized, cannot load tool names")
            return

        try:
            tools = await self.client.list_tools()
        except Exception as e:
            logger.warning(f"⚠️ Failed to list MCP tools, using logical names: {e}")
            # Fall back to logical names
            self.tool_names = {
                "configure": "configure",
                "narrate_text": "narrate_text",
                "list_characters": "list_characters",
                "get_config_status": "get_config_status",
            }
            return

        # Extract tool names from FastMCP client's response
        names: list[str] = []
        if isinstance(tools, dict):
            names = list(tools.keys())
        else:
            for t in tools:
                if hasattr(t, "name"):
                    names.append(t.name)  # type: ignore[attr-defined]
                else:
                    names.append(str(t))

        def resolve(logical: str) -> str:
            # Exact match first
            if logical in names:
                return logical
            # Then suffix match, e.g. *_narrate_text
            suffix = f"_{logical}"
            for n in names:
                if n.endswith(suffix):
                    return n
            # Fallback to logical name
            logger.warning(
                f"⚠️ Could not resolve tool name for '{logical}', "
                f"falling back to logical name"
            )
            return logical

        self.tool_names = {
            "configure": resolve("configure"),
            "narrate_text": resolve("narrate_text"),
            "list_characters": resolve("list_characters"),
            "get_config_status": resolve("get_config_status"),
        }

        logger.info(
            "🧰 Resolved MCP tool names: "
            + ", ".join(f"{k} -> {v}" for k, v in self.tool_names.items())
        )

    async def _check_server_running(self, url: str) -> bool:
        """Check if MCP server is running by attempting HTTP connection."""
        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                # Try to connect to the server endpoint
                response = await client.get(url)
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

    async def _start_server(self, project_root: Path, narrator_path: Path, url: str):
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
            if await self._check_server_running(url):
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

        # Terminate server process if we started it (only for local HTTP mode)
        if self.server_process:
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
        if self.tts_provider:
            config_args["tts_provider"] = self.tts_provider

        provider_info = f"base_url={self.base_url}" if self.base_url else "provider=OpenAI"
        config_info = (
            f"model={self.model or 'default'}, voice={self.voice or 'default'}, "
            f"mode={self.mode or 'chat'}, character={self.character or 'default'}, "
            f"{provider_info}, tts_provider={self.tts_provider or 'auto'}"
        )

        logger.info(f"🔑 Configuring server ({config_info})...")
        tool_name = self.tool_names.get("configure", "configure")
        logger.info(f"🛠 Using configure tool: {tool_name}")
        result = await self.client.call_tool(tool_name, config_args)
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
            streaming_chunks = 0

            async def progress_handler(progress, total, message):
                nonlocal streaming_chunks
                if not message:
                    return
                try:
                    payload = json.loads(message)
                except json.JSONDecodeError:
                    logger.debug(f"⚠️ Failed to parse progress payload: {message}")
                    return

                if payload.get("type") != "chunk":
                    return

                chunk_index = payload.get("index") or (streaming_chunks + 1)
                chunk_text = (payload.get("text") or "").strip()
                audio_b64 = payload.get("audio") or ""

                if chunk_text:
                    preview = chunk_text if len(chunk_text) <= 120 else chunk_text[:117] + "..."
                    logger.info(f"🗣️ Stream chunk #{chunk_index}: {preview}")

                if not audio_b64:
                    return

                try:
                    audio_bytes = base64.b64decode(audio_b64)
                except Exception as e:
                    logger.warning(f"⚠️ Failed to decode streaming audio chunk #{chunk_index}: {e}")
                    return

                self.audio_player.add_chunk(audio_bytes)
                streaming_chunks += 1

            # Call narrate_text tool (resolved based on available tools)
            tool_name = self.tool_names.get("narrate_text", "narrate_text")
            logger.info(f"🎤 Using narrate_text tool: {tool_name}")
            try:
                result = await self.client.call_tool(
                    tool_name,
                    {"prompt": text},
                    progress_handler=progress_handler,
                )
            except ToolError as e:
                # Log detailed error information
                error_detail = str(e)
                logger.error(f"❌ MCP tool error: {error_detail}")
                # Try to get more details from the exception
                if hasattr(e, 'message'):
                    logger.error(f"   Error message: {e.message}")
                if hasattr(e, 'code'):
                    logger.error(f"   Error code: {e.code}")
                raise

            # Normalize result into a Python dict with text/audio/format fields.
            response_data: dict[str, Any]

            # FastMCP: CallToolResult with .data attribute
            if hasattr(result, "data") and getattr(result, "data") is not None:
                data = getattr(result, "data")
                if isinstance(data, dict):
                    response_data = data
                elif isinstance(data, str):
                    if not data.strip():
                        logger.warning("⚠️ narrate_text returned empty string data")
                        response_data = {}
                    else:
                        response_data = json.loads(data)
                else:
                    logger.warning(f"⚠️ Unexpected result.data type: {type(data)}")
                    response_data = {}
            # Plain dict
            elif isinstance(result, dict):
                response_data = result
            # Plain string
            elif isinstance(result, str):
                if not result.strip():
                    logger.warning("⚠️ narrate_text returned empty string result")
                    response_data = {}
                else:
                    response_data = json.loads(result)
            else:
                # Fallback: try to get from content (SSE-style responses)
                if hasattr(result, "content") and getattr(result, "content"):
                    content = getattr(result, "content")
                    first = content[0]
                    if hasattr(first, "text"):
                        text_val = first.text  # type: ignore[attr-defined]
                    else:
                        text_val = str(first)
                    if text_val and isinstance(text_val, str):
                        try:
                            response_data = json.loads(text_val)
                        except Exception:
                            logger.warning(
                                f"⚠️ Failed to parse content text as JSON, using empty response. "
                                f"text={text_val!r}"
                            )
                            response_data = {}
                    else:
                        response_data = {}
                else:
                    logger.warning(
                        f"⚠️ Unexpected narrate_text result type: {type(result)}, "
                        f"value={result!r}"
                    )
                    response_data = {}

            # Check for error in response
            if "error" in response_data:
                error_msg = response_data.get("error", "Unknown error")
                logger.error(f"❌ Narration error: {error_msg}")
                self.narrations_completed += 1
                return

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

            if len(audio_bytes) > 0 and streaming_chunks == 0:
                self.audio_player.add_chunk(audio_bytes)

            self.narrations_completed += 1
            if streaming_chunks > 0:
                logger.info(
                    f"✅ Narration #{self.narrations_completed} complete: "
                    f"{len(generated_text)} chars, streamed {streaming_chunks} chunk(s)"
                )
            else:
                logger.info(
                    f"✅ Narration #{self.narrations_completed} complete: "
                    f"{len(generated_text)} chars, {len(audio_bytes)} bytes {audio_format}"
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
    Uses list-based accumulation for O(1) append instead of O(n) string concatenation.
    """

    def __init__(self, min_window_seconds=2.0, pause_threshold=5.0):
        self._chunks: list[str] = []  # Use list for efficient append
        self._buffer_len = 0  # Track total length without joining
        self.window_start_time = None
        self.last_data_time = None
        self.min_window_seconds = min_window_seconds
        self.pause_threshold = pause_threshold
        self.force_flush_all = False

    @property
    def buffer(self) -> str:
        """Get the current buffer content (joins chunks on demand)."""
        if not self._chunks:
            return ""
        if len(self._chunks) == 1:
            return self._chunks[0]
        # Join and consolidate to single chunk for efficiency
        joined = ''.join(self._chunks)
        self._chunks = [joined] if joined else []
        return joined

    @buffer.setter
    def buffer(self, value: str):
        """Set the buffer content."""
        self._chunks = [value] if value else []
        self._buffer_len = len(value) if value else 0

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
        if text:
            self._chunks.append(text)
            self._buffer_len += len(text)
        if self.window_start_time is None:
            self.window_start_time = current_time
        self.last_data_time = current_time

    def has_complete_lines(self) -> bool:
        """Check if buffer has complete lines."""
        if not self._chunks:
            return False
        # Check each chunk for newline to avoid full join
        for chunk in self._chunks:
            if '\n' in chunk:
                return True
        return False

    def should_flush(self, current_time: float) -> bool:
        """Determine if buffer should be flushed."""
        if self._buffer_len == 0:
            return False

        has_complete = self.has_complete_lines()
        ALLOW_FLUSH_WITHOUT_NEWLINES = True

        # Check if minimum time window is exceeded
        if self.window_start_time and \
           (current_time - self.window_start_time) >= self.min_window_seconds:
            if has_complete:
                self.force_flush_all = False
                return True
            elif ALLOW_FLUSH_WITHOUT_NEWLINES and self._buffer_len > 0:
                self.force_flush_all = True
                return True

        # Check if pause threshold is exceeded
        if self.last_data_time and \
           (current_time - self.last_data_time) >= self.pause_threshold:
            if has_complete:
                self.force_flush_all = False
                return True
            if self._buffer_len > 0:
                self.force_flush_all = True
                return True

        return False

    def flush(self) -> str:
        """Flush buffer, return complete lines."""
        if self._buffer_len == 0:
            return ""

        # Join all chunks
        buffer_str = self.buffer

        last_newline = buffer_str.rfind('\n')

        if last_newline == -1 or self.force_flush_all:
            result = buffer_str
            self._chunks = []
            self._buffer_len = 0
            self.window_start_time = None
            self.last_data_time = None
            self.force_flush_all = False
        else:
            result = buffer_str[:last_newline + 1]
            remaining = buffer_str[last_newline + 1:]
            self._chunks = [remaining] if remaining else []
            self._buffer_len = len(remaining)

            if remaining:
                self.window_start_time = time.time()
            else:
                self.window_start_time = None
                self.last_data_time = None

        safe_text, tail = self._split_incomplete_escape_tail(result)
        if tail:
            if self._chunks:
                self._chunks.insert(0, tail)
            else:
                self._chunks = [tail]
            self._buffer_len += len(tail)
            if self.window_start_time is None:
                self.window_start_time = time.time()
            self.last_data_time = time.time()
            if not safe_text:
                return ""

        return safe_text

    def has_data(self) -> bool:
        """Check if buffer has data."""
        return self._buffer_len > 0

    def flush_all(self) -> str:
        """Force flush all buffer contents."""
        if self._buffer_len == 0:
            return ""

        result = self.buffer
        self._chunks = []
        self._buffer_len = 0
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


class AsyncFdReader:
    """Async file descriptor reader using event loop's add_reader for efficient I/O."""

    def __init__(self, fd: int, loop: asyncio.AbstractEventLoop):
        self.fd = fd
        self.loop = loop
        self._pending_future: asyncio.Future | None = None

    async def read(self, size: int = 4096) -> bytes:
        """Read data from file descriptor asynchronously."""
        future = self.loop.create_future()
        self._pending_future = future

        def _on_readable():
            self.loop.remove_reader(self.fd)
            if future.done():
                return
            try:
                data = os.read(self.fd, size)
                future.set_result(data)
            except OSError as e:
                future.set_exception(e)

        self.loop.add_reader(self.fd, _on_readable)
        try:
            return await future
        except asyncio.CancelledError:
            self.loop.remove_reader(self.fd)
            raise
        finally:
            self._pending_future = None

    def cancel(self):
        """Cancel any pending read operation."""
        try:
            self.loop.remove_reader(self.fd)
        except Exception:
            pass
        if self._pending_future and not self._pending_future.done():
            self._pending_future.cancel()


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

    # Track background narration tasks to avoid blocking I/O loop
    narration_tasks: list[asyncio.Task] = []
    # Limit concurrent narration tasks to prevent overwhelming the system
    narration_semaphore = asyncio.Semaphore(2)
    # Timeout for individual narration requests (prevent indefinite blocking)
    NARRATION_TIMEOUT = 60.0  # 60 seconds max per narration

    async def send_narration_async(text: str):
        """Send narration in background without blocking I/O loop."""
        try:
            # Use asyncio.timeout to prevent tasks from blocking forever
            async with asyncio.timeout(NARRATION_TIMEOUT):
                async with narration_semaphore:
                    await bridge.send_chunk(text)
        except asyncio.TimeoutError:
            logger.warning(f"⏰ Narration timed out after {NARRATION_TIMEOUT}s, skipping")
        except Exception as e:
            logger.error(f"❌ Background narration failed: {e}")

    def schedule_narration(text: str):
        """Schedule a narration task and track it."""
        task = asyncio.create_task(send_narration_async(text))
        narration_tasks.append(task)
        # Clean up completed tasks periodically to avoid memory growth
        completed = [t for t in narration_tasks if t.done()]
        for t in completed:
            narration_tasks.remove(t)

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

        # Get event loop for async I/O
        loop = asyncio.get_event_loop()

        # Create async readers for efficient I/O
        pty_reader = AsyncFdReader(master_fd, loop)
        stdin_reader = AsyncFdReader(sys.stdin.fileno(), loop) if stdin_is_tty else None

        # Async I/O loop using concurrent tasks for better responsiveness
        try:
            while True:
                current_time = time.time()

                # Check if buffer should be flushed
                if text_buffer.should_flush(current_time):
                    buffered_text = text_buffer.flush()
                    if buffered_text:
                        clean = clean_text(buffered_text)
                        if clean:
                            schedule_narration(clean)

                # Check if command finished
                if cmd_proc.poll() is not None:
                    # Read remaining data with short timeout
                    while True:
                        ready, _, _ = select.select([master_fd], [], [], 0.1)
                        if not ready:
                            break
                        try:
                            data = os.read(master_fd, 4096)
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
                            schedule_narration(clean)
                    break

                # Create concurrent read tasks for PTY and stdin
                read_tasks = []
                pty_task = asyncio.create_task(pty_reader.read(4096))
                read_tasks.append(('pty', pty_task))

                if stdin_reader:
                    stdin_task = asyncio.create_task(stdin_reader.read(1024))
                    read_tasks.append(('stdin', stdin_task))

                # Wait for any read to complete with timeout for buffer flush checks
                try:
                    done, pending = await asyncio.wait(
                        [t for _, t in read_tasks],
                        timeout=0.1,
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    # Cancel pending tasks
                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

                    # Process completed tasks
                    for name, task in read_tasks:
                        if task in done:
                            try:
                                data = task.result()
                                if not data:
                                    # EOF - break loop
                                    break

                                if name == 'pty':
                                    # Display PTY output to terminal
                                    sys.stdout.buffer.write(data)
                                    sys.stdout.buffer.flush()
                                    # Buffer for narration
                                    text = data.decode('utf-8', errors='replace')
                                    text_buffer.add_data(text, current_time)
                                elif name == 'stdin':
                                    # Forward user input to PTY
                                    os.write(master_fd, data)
                            except OSError:
                                break
                    else:
                        # No break occurred, continue loop
                        continue
                    # Break occurred in inner loop
                    break

                except asyncio.TimeoutError:
                    # Timeout is expected - allows buffer flush checks
                    continue

        except KeyboardInterrupt:
            logger.info("⚠️ Interrupted by user")
        finally:
            restore_terminal()

            # Cancel any pending async readers
            pty_reader.cancel()
            if stdin_reader:
                stdin_reader.cancel()

            # Process final remaining buffer
            if text_buffer.has_data():
                buffered_text = text_buffer.flush_all()
                if buffered_text:
                    clean = clean_text(buffered_text)
                    if clean:
                        schedule_narration(clean)

            # Wait for all pending narration tasks to complete
            if narration_tasks:
                pending = [t for t in narration_tasks if not t.done()]
                if pending:
                    logger.info(f"⏳ Waiting for {len(pending)} pending narration tasks...")
                    await asyncio.gather(*pending, return_exceptions=True)

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
                     tts_provider: str | None):
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
        tts_provider=tts_provider,
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

Transport is auto-selected based on NARRATOR_REMOTE_MCP_URL:
  - Not set: stdio (local mode, recommended)
  - localhost URL: streamable-http
  - Remote URL: sse
        '''
    )
    parser.add_argument('command', nargs=argparse.REMAINDER,
                       help='Command to run in PTY (e.g., claude, python -i, bash)')
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
    tts_api_key = os.getenv("TTS_API_KEY")

    base_url = None
    default_headers = None
    api_key = None

    # TTS API key: prefer TTS_API_KEY, fallback to OPENAI_API_KEY
    if tts_api_key:
        logger.info("🔊 Using TTS_API_KEY for TTS")
    elif openai_api_key:
        tts_api_key = openai_api_key
        logger.info("🔊 Using OPENAI_API_KEY for TTS (fallback)")
    else:
        logger.error("❌ TTS requires API key")
        logger.error("Please set either TTS_API_KEY or OPENAI_API_KEY in .env file")
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
    voice = os.getenv("TTS_VOICE")
    mode = os.getenv("MODE")
    character = os.getenv("CHARACTER")
    tts_provider = os.getenv("TTS_PROVIDER")
    if tts_provider:
        logger.info(f"🎛️ TTS provider set to {tts_provider}")

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
        tts_provider=tts_provider,
    ))

    logger.info("✅ Bridge session complete")
