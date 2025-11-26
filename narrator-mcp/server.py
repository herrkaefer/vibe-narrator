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
from characters import get_character, list_characters
from llm import stream_llm, CHAT_MODE_SYSTEM_PROMPT, NARRATION_MODE_SYSTEM_PROMPT
from session import Session
from tts import stream_tts

# Setup logging
script_dir = Path(__file__).parent.absolute()
log_dir = script_dir / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
narrate_log_file = log_dir / f"narrator_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)

file_handler = logging.FileHandler(narrate_log_file, encoding="utf-8")
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(file_formatter)

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
    api_key: str,
    model: str | None = None,
    voice: str | None = None,
    mode: str | None = None,
    character: str | None = None,
    base_url: str | None = None,
    default_headers: dict | None = None,
    tts_api_key: str | None = None,
) -> str:
    """Configure API credentials and narration settings for the session."""
    ctx = get_context()
    ctx.session.api_key = api_key
    if model is not None:
        ctx.session.model = model
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

    # Log all configuration (except api_key for security)
    config_parts = [
        f"model={ctx.session.model}",
        f"voice={ctx.session.voice}",
        f"mode={ctx.session.mode}",
        f"character={ctx.session.character or 'default'}",
    ]
    if ctx.session.base_url:
        config_parts.append(f"base_url={ctx.session.base_url}")
    else:
        config_parts.append("provider=OpenAI")
    if ctx.session.default_headers:
        headers_str = ", ".join(f"{k}={v[:20]}..." if len(str(v)) > 20 else f"{k}={v}"
                               for k, v in ctx.session.default_headers.items())
        config_parts.append(f"default_headers=[{headers_str}]")

    logging.info(f"✅ Session configured: {', '.join(config_parts)}")

    return "Configuration updated successfully"


@mcp.tool()
async def narrate(prompt: str) -> str:
    """Convert text to narrated speech using LLM and TTS."""
    ctx = get_context()

    if not prompt:
        raise ValueError("Missing prompt parameter")
    if not ctx.session.api_key:
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
    chars = list_characters()
    logging.info(f"📋 Listing {len(chars)} available characters")
    return json.dumps({"characters": chars})


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
                "api_key": ctx.session.api_key,
                "model": ctx.session.model,
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

                # TTS always uses OpenAI API with dedicated tts_api_key
                # Don't pass base_url and default_headers (use OpenAI default endpoint)
                tts_params = {
                    "text_block": block,
                    "api_key": ctx.session.tts_api_key or ctx.session.api_key,
                    "voice": ctx.session.voice,
                    "instructions": character.tts_instructions,
                }
                # TTS doesn't use OpenRouter's base_url and headers, always uses OpenAI default endpoint

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
    mcp.run(transport="streamable-http", port=8000, path="/mcp")


__all__ = ["mcp"]
