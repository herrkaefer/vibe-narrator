"""MCP server using FastMCP with streamable-http transport."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import openai
from fastmcp import FastMCP

from chunker import Chunker
from characters import get_character, get_characters_list
from llm import stream_llm, CHAT_MODE_SYSTEM_PROMPT, NARRATION_MODE_SYSTEM_PROMPT
from session import Session
from tts import stream_tts, detect_tts_provider

# Setup logging
script_dir = Path(__file__).parent.absolute()
log_dir = script_dir / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
narrate_log_file = log_dir / f"narrator_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# Check if running in stdio mode
import os
is_stdio_mode = os.getenv("MCP_TRANSPORT") == "stdio"

# Configure log handlers
handlers = []
# In stdio mode, don't output to stderr (to avoid interfering with terminal output)
# In streamable-http mode, output to stderr for debugging
if not is_stdio_mode:
    handlers.append(logging.StreamHandler(sys.stderr))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=handlers,
)

file_handler = logging.FileHandler(narrate_log_file, encoding="utf-8")
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(file_formatter)
# Add file handler to root logger
logging.getLogger().addHandler(file_handler)

# In stdio mode, suppress FastMCP and OpenAI log output to stderr
if is_stdio_mode:
    # Suppress FastMCP logs
    logging.getLogger("fastmcp").setLevel(logging.WARNING)
    # Suppress OpenAI HTTP request logs
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

narrate_logger = logging.getLogger("narrate")
narrate_logger.setLevel(logging.INFO)
narrate_logger.addHandler(file_handler)


@dataclass
class AppContext:
    """Application context with session state."""
    session: Session
    chunker: Chunker


# Global context (set by lifespan)
_app_context: AppContext | None = None


@asynccontextmanager
async def app_lifespan(mcp: FastMCP):
    """Initialize persistent session state."""
    global _app_context
    ctx = AppContext(
        session=Session(),
        chunker=Chunker(max_tokens=12, sentence_boundary=True)
    )
    _app_context = ctx
    logging.info("🚀 Narrator MCP Server initialized")
    logging.info(f"📝 Narrate logs: {narrate_log_file}")
    try:
        yield ctx
    finally:
        _app_context = None
        logging.info("🛑 Narrator MCP Server shutting down")


# Create FastMCP server
mcp = FastMCP(name="narrator-mcp", lifespan=app_lifespan)


def get_context() -> AppContext:
    """Get the application context."""
    if _app_context is None:
        raise RuntimeError("Application context not initialized")
    return _app_context


@mcp.tool()
async def configure(
    llm_api_key: str,
    llm_model: str | None = None,
    voice: str | None = None,
    mode: str | None = None,
    character: str | None = None,
    base_url: str | None = None,
    default_headers: dict | None = None,
    tts_api_key: str | None = None,
    tts_provider: str | None = None,
) -> str:
    """Configure API credentials and narration settings for the session."""
    ctx = get_context()
    ctx.session.llm_api_key = llm_api_key
    if llm_model is not None:
        ctx.session.llm_model = llm_model
    if voice is not None:
        ctx.session.voice = voice
    if mode is not None:
        ctx.session.mode = mode
    if character is not None:
        ctx.session.character = character
    if base_url is not None:
        ctx.session.base_url = base_url
    if default_headers is not None:
        ctx.session.default_headers = default_headers
    if tts_api_key is not None:
        ctx.session.tts_api_key = tts_api_key
    else:
        # If tts_api_key is None, set it to llm_api_key
        ctx.session.tts_api_key = llm_api_key

    # Set TTS provider (auto-detect if not provided)
    if tts_provider is not None:
        ctx.session.tts_provider = tts_provider
    elif ctx.session.tts_api_key:
        # Auto-detect provider from API key format
        ctx.session.tts_provider = detect_tts_provider(ctx.session.tts_api_key)
    else:
        ctx.session.tts_provider = None

    # Log all configuration (except llm_api_key for security)
    config_parts = [
        f"model={ctx.session.llm_model}",
        f"voice={ctx.session.voice}",
        f"mode={ctx.session.mode}",
        f"character={ctx.session.character or 'default'}",
    ]
    if ctx.session.base_url:
        config_parts.append(f"base_url={ctx.session.base_url}")
    else:
        config_parts.append("llm_provider=OpenAI")
    if ctx.session.default_headers:
        headers_str = ", ".join(f"{k}={v[:20]}..." if len(str(v)) > 20 else f"{k}={v}"
                               for k, v in ctx.session.default_headers.items())
        config_parts.append(f"default_headers=[{headers_str}]")

    # Add TTS provider info
    tts_provider_name = ctx.session.tts_provider or "auto-detect"
    config_parts.append(f"tts_provider={tts_provider_name}")

    logging.info(f"✅ Session configured: {', '.join(config_parts)}")

    return "Configuration updated successfully"


@mcp.tool()
async def narrate(prompt: str) -> str:
    """Convert text to narrated speech using LLM and TTS."""
    ctx = get_context()

    if not prompt:
        raise ValueError("Missing prompt parameter")
    if not ctx.session.llm_api_key:
        raise ValueError("Not configured. Call 'configure' tool first")
    if not ctx.session.tts_api_key:
        raise ValueError("Not configured. Call 'configure' tool first")

    logging.info("🎧 Narrate request received")
    narrate_logger.info(f"📝 Narrate text:\n{prompt}")

    # Generate narration
    text, audio_bytes = await generate_narration(ctx, prompt)

    # Return as JSON with base64-encoded audio
    result = {
        "text": text,
        "audio": base64.b64encode(audio_bytes).decode('utf-8'),
        "format": "mp3"
    }

    logging.info(f"✅ Narration complete: {len(text)} chars, {len(audio_bytes)} bytes audio")

    return json.dumps(result)


@mcp.tool()
async def list_characters() -> str:
    """List available character personalities."""
    chars = get_characters_list()
    logging.info(f"📋 Listing {len(chars)} available characters")
    return json.dumps({"characters": chars})


@mcp.tool()
async def get_config_status() -> str:
    """Get the current configuration status for debugging."""
    ctx = get_context()
    session = ctx.session

    # Build status dictionary
    status = {
        "has_api_key": session.llm_api_key is not None,
        "has_tts_api_key": session.tts_api_key is not None,
        "is_configured": session.llm_api_key is not None and session.tts_api_key is not None,
        "session": {
            "model": session.llm_model,
            "voice": session.voice,
            "mode": session.mode,
            "character": session.character or "default",
            "base_url": session.base_url,
            "has_default_headers": session.default_headers is not None,
            "tts_provider": session.tts_provider or "auto-detect",
        }
    }

    # Add default_headers keys if present (without values for security)
    if session.default_headers:
        status["session"]["default_headers_keys"] = list(session.default_headers.keys())

    logging.info("🔍 Config status requested")
    return json.dumps(status)


async def generate_narration(ctx: AppContext, prompt: str) -> tuple[str, bytes]:
    """
    Generate narrated speech from text prompt.
    Returns (generated_text, audio_mp3_bytes)
    """
    character = get_character(ctx.session.character)

    tts_queue: asyncio.Queue[str | None] = asyncio.Queue()
    generated_text_tokens: list[str] = []
    audio_chunks: list[bytes] = []

    async def run_llm() -> None:
        """Stream LLM tokens and chunk for TTS."""
        try:
            token_count = 0

            # Prepare stream parameters
            stream_params: dict[str, Any] = {
                "prompt": prompt,
                "api_key": ctx.session.llm_api_key,
                "model": ctx.session.llm_model,
                "character": character
            }

            if ctx.session.base_url:
                stream_params["base_url"] = ctx.session.base_url
            if ctx.session.default_headers:
                stream_params["default_headers"] = ctx.session.default_headers

            # Select system prompt and max tokens based on mode
            if ctx.session.mode == "narration":
                stream_params["system_prompt"] = NARRATION_MODE_SYSTEM_PROMPT
                stream_params["max_tokens"] = 25
            else:  # chat mode
                stream_params["system_prompt"] = CHAT_MODE_SYSTEM_PROMPT
                stream_params["max_tokens"] = 20

            # Stream LLM tokens
            async for token in stream_llm(**stream_params):
                token_count += 1
                narrate_logger.debug(f"📝 LLM token #{token_count}: {repr(token)}")
                generated_text_tokens.append(token)

                # Chunk tokens for TTS
                block = ctx.chunker.add_token(token)
                if block:
                    stripped = block.strip().strip('"').strip("'").strip()
                    if stripped:
                        narrate_logger.info(f"📦 Chunk ready for TTS ({len(block)} chars): {repr(block)}")
                        await tts_queue.put(block)
                    else:
                        narrate_logger.info(f"⏭️ Skipping empty chunk: {repr(block)}")

            narrate_logger.info(f"✅ LLM streaming complete ({token_count} tokens)")

            # Flush remaining tokens
            leftover = ctx.chunker.flush()
            if leftover:
                stripped = leftover.strip().strip('"').strip("'").strip()
                if stripped:
                    narrate_logger.info(f"📦 Final chunk for TTS ({len(leftover)} chars): {repr(leftover)}")
                    await tts_queue.put(leftover)
                else:
                    narrate_logger.info(f"⏭️ Skipping empty final chunk: {repr(leftover)}")

            await tts_queue.put(None)  # Signal completion

        except (openai.RateLimitError, openai.APIError) as e:
            # Build detailed error information
            error_details = [f"OpenAI API error: {str(e)}"]

            # Add error type
            error_details.append(f"Error type: {type(e).__name__}")

            # Add status code (if available)
            if hasattr(e, 'status_code'):
                error_details.append(f"Status code: {e.status_code}")

            # Add error code (if available)
            if hasattr(e, 'code'):
                error_details.append(f"Error code: {e.code}")

            # Add response body (if available)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    if hasattr(e.response, 'text'):
                        error_details.append(f"Response: {e.response.text}")
                    elif hasattr(e.response, 'json'):
                        error_details.append(f"Response: {e.response.json()}")
                except Exception:
                    pass

            # Add request information (if available)
            if hasattr(e, 'request') and e.request is not None:
                try:
                    if hasattr(e.request, 'url'):
                        error_details.append(f"Request URL: {e.request.url}")
                except Exception:
                    pass

            error_msg = " | ".join(error_details)
            narrate_logger.error(f"❌ LLM error: {error_msg}")
            logging.error(f"❌ LLM error: {error_msg}")
            await tts_queue.put(None)
            raise
        except Exception as e:
            error_msg = f"LLM error: {str(e)}"
            narrate_logger.error(f"❌ {error_msg}", exc_info=True)
            logging.error(f"❌ {error_msg}", exc_info=True)
            await tts_queue.put(None)
            raise

    async def run_tts() -> None:
        """Stream TTS audio for each text chunk."""
        try:
            tts_chunk_count = 0

            while True:
                block = await tts_queue.get()
                if block is None:
                    break

                tts_chunk_count += 1
                narrate_logger.info(f"🎤 Sending to TTS #{tts_chunk_count} ({len(block)} chars): {repr(block)}")

                # Accumulate audio chunks for this text block
                audio_buffer = bytearray()
                audio_fragment_count = 0

                # TTS supports both OpenAI and ElevenLabs
                tts_params = {
                    "text_block": block,
                    "api_key": ctx.session.tts_api_key or ctx.session.llm_api_key,
                    "voice": ctx.session.voice,
                    "instructions": character.tts_instructions,
                    "tts_provider": ctx.session.tts_provider,
                }
                # For OpenAI, don't pass base_url and default_headers (use OpenAI default endpoint)
                # For ElevenLabs, these are not used

                async for audio_chunk in stream_tts(**tts_params):
                    audio_fragment_count += 1
                    audio_buffer.extend(audio_chunk)
                    narrate_logger.debug(f"   🎵 Audio fragment #{audio_fragment_count}: {len(audio_chunk)} bytes")

                if audio_buffer:
                    narrate_logger.info(
                        f"   ✅ Complete MP3 #{tts_chunk_count}: {len(audio_buffer)} bytes "
                        f"(from {audio_fragment_count} fragments)"
                    )
                    audio_chunks.append(bytes(audio_buffer))

        except (openai.RateLimitError, openai.APIError) as e:
            # Build detailed error information
            error_details = [f"OpenAI TTS API error: {str(e)}"]

            # Add error type
            error_details.append(f"Error type: {type(e).__name__}")

            # Add status code (if available)
            if hasattr(e, 'status_code'):
                error_details.append(f"Status code: {e.status_code}")

            # Add error code (if available)
            if hasattr(e, 'code'):
                error_details.append(f"Error code: {e.code}")

            # Add response body (if available)
            if hasattr(e, 'response') and e.response is not None:
                try:
                    if hasattr(e.response, 'text'):
                        error_details.append(f"Response: {e.response.text}")
                    elif hasattr(e.response, 'json'):
                        error_details.append(f"Response: {e.response.json()}")
                except Exception:
                    pass

            error_msg = " | ".join(error_details)
            narrate_logger.error(f"❌ TTS error: {error_msg}")
            logging.error(f"❌ TTS error: {error_msg}")
            raise
        except Exception as e:
            error_msg = f"TTS error: {str(e)}"
            narrate_logger.error(f"❌ {error_msg}", exc_info=True)
            logging.error(f"❌ {error_msg}", exc_info=True)
            raise

    # Run LLM and TTS concurrently
    await asyncio.gather(run_llm(), run_tts())

    # Combine results
    full_text = ''.join(generated_text_tokens)
    full_audio = b''.join(audio_chunks)

    return full_text, full_audio


if __name__ == "__main__":
    import os
    # Determine transport mode via environment variable, default to streamable-http (remote mode)
    transport = os.getenv("MCP_TRANSPORT", "streamable-http")

    if transport == "stdio":
        # Local stdio mode
        mcp.run(transport="stdio")
    else:
        # Remote streamable-http mode
        mcp.run(transport="streamable-http", port=8000, path="/mcp")


__all__ = ["mcp"]
