"""JSON-RPC MCP server over stdin/stdout with session-scoped API keys."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from chunker import Chunker
from events import send_audio_event, send_text_event
from llm import stream_llm, CHAT_MODE_SYSTEM_PROMPT, NARRATION_MODE_SYSTEM_PROMPT
from session import Session
from tts import stream_tts
from characters import get_character, get_default_character

import openai

session = Session()
chunker = Chunker(max_tokens=12, sentence_boundary=True)
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

shutting_down = False


def signal_handler(sig, frame) -> None:
    """Handle termination signals and notify the client."""
    del frame
    global shutting_down
    if shutting_down:
        return
    shutting_down = True

    signal_name = signal.Signals(sig).name
    logging.info("🛑 Received %s signal, shutting down gracefully...", signal_name)
    narrate_logger.info("🛑 MCP Server shutting down (signal: %s)", signal_name)

    try:
        payload = {
            "jsonrpc": "2.0",
            "method": "notifications/shutdown",
            "params": {"reason": "received_signal", "signal": signal_name},
        }
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()
        logging.info("📤 Sent shutdown notification to client")
    except Exception as exc:
        logging.warning("⚠️ Failed to send shutdown notification: %s", exc)

    time.sleep(0.1)
    sys.exit(0)


signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


async def send(payload: Dict[str, Any]) -> None:
    """Writes a JSON payload to stdout."""
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


async def handle_config(msg: Dict[str, Any]) -> None:
    params = msg.get("params") or {}
    api_key = params.get("api_key")
    if not api_key:
        await send(
            {
                "jsonrpc": "2.0",
                "error": {"code": 1, "message": "Missing API key in config request."},
                "id": msg.get("id"),
            }
        )
        return

    session.api_key = api_key
    session.model = params.get("model", session.model)
    session.voice = params.get("voice", session.voice)
    session.mode = params.get("mode", session.mode)
    session.character = params.get("character", session.character)
    session.base_url = params.get("base_url", session.base_url)
    session.default_headers = params.get("default_headers", session.default_headers)

    # Log configuration
    provider_info = f"base_url={session.base_url}" if session.base_url else "provider=OpenAI"
    logging.info(f"✅ Session configured (model={session.model}, voice={session.voice}, mode={session.mode}, character={session.character or 'default'}, {provider_info})")

    await send({"jsonrpc": "2.0", "result": "ok", "id": msg.get("id")})


async def handle_narrate(msg: Dict[str, Any]) -> None:
    params = msg.get("params") or {}
    prompt = params.get("prompt")
    if not prompt:
        await send(
            {
                "jsonrpc": "2.0",
                "error": {"code": 2, "message": "Missing prompt for narrate request."},
                "id": msg.get("id"),
            }
        )
        return

    if not session.api_key:
        await send(
            {
                "jsonrpc": "2.0",
                "error": {"code": 3, "message": "API key not set. Send 'config' first."},
                "id": msg.get("id"),
            }
        )
        return

    tts_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
    error_occurred = False  # Flag to track if an error response was already sent
    logging.info("🎧 Narrate request received")
    narrate_logger.info("📝 Narrate text:\n%s", prompt)

    # Get current character from session, or use default
    character = get_character(session.character)
    logging.info(f"🎭 Using character: {character.name}")
    narrate_logger.info(f"🎭 Character: {character.name} (id: {character.id})")

    async def run_llm() -> None:
        nonlocal error_occurred
        try:
            token_count = 0
            # Determine system prompt based on mode
            stream_params = {
                "prompt": prompt,
                "api_key": session.api_key,
                "model": session.model
            }

            # Add base_url and headers if configured
            if session.base_url:
                stream_params["base_url"] = session.base_url
            if session.default_headers:
                stream_params["default_headers"] = session.default_headers

            # Select system prompt based on mode
            if session.mode == "narration":
                stream_params["system_prompt"] = NARRATION_MODE_SYSTEM_PROMPT
                # Limit max_tokens for narration mode to keep responses brief
                stream_params["max_tokens"] = 25
            elif session.mode == "chat":
                stream_params["system_prompt"] = CHAT_MODE_SYSTEM_PROMPT
                # Chat mode can be longer, but still limit to avoid excessive output
                stream_params["max_tokens"] = 20
            # If no explicit mode, llm.py will use its default (chat mode)

            # Add character for role-playing
            stream_params["character"] = character

            async for token in stream_llm(**stream_params):
                token_count += 1
                narrate_logger.debug("📝 LLM token #%d: %s", token_count, repr(token))
                await send_text_event(send, token)
                block = chunker.add_token(token)
                if block:
                    # Strip whitespace and quotes to check if content is meaningful
                    stripped = block.strip().strip('"').strip("'").strip()
                    if stripped:  # Only send to TTS if there's actual content
                        narrate_logger.info("📦 Chunk ready for TTS (%d chars): %s", len(block), repr(block))
                        await tts_queue.put(block)
                    else:
                        narrate_logger.info("⏭️ Skipping empty chunk: %s", repr(block))

            narrate_logger.info("✅ LLM streaming complete (%d tokens)", token_count)
            leftover = chunker.flush()
            if leftover:
                # Strip whitespace and quotes to check if content is meaningful
                stripped = leftover.strip().strip('"').strip("'").strip()
                if stripped:  # Only send to TTS if there's actual content
                    narrate_logger.info("📦 Final chunk for TTS (%d chars): %s", len(leftover), repr(leftover))
                    await tts_queue.put(leftover)
                else:
                    narrate_logger.info("⏭️ Skipping empty final chunk: %s", repr(leftover))

            await tts_queue.put(None)
        except openai.RateLimitError as e:
            error_occurred = True
            error_msg = f"OpenAI API rate limit exceeded: {str(e)}"
            narrate_logger.error(f"❌ LLM rate limit error: {error_msg}")
            logging.error(f"❌ LLM rate limit error: {error_msg}")
            await tts_queue.put(None)  # Signal TTS to stop
            await send({
                "jsonrpc": "2.0",
                "error": {
                    "code": 4,
                    "message": error_msg
                },
                "id": msg.get("id")
            })
        except openai.APIError as e:
            error_occurred = True
            error_msg = f"OpenAI API error: {str(e)}"
            narrate_logger.error(f"❌ LLM API error: {error_msg}")
            logging.error(f"❌ LLM API error: {error_msg}")
            await tts_queue.put(None)  # Signal TTS to stop
            await send({
                "jsonrpc": "2.0",
                "error": {
                    "code": 4,
                    "message": error_msg
                },
                "id": msg.get("id")
            })
        except Exception as e:
            error_occurred = True
            error_msg = f"LLM error: {str(e)}"
            narrate_logger.error(f"❌ LLM error: {error_msg}", exc_info=True)
            logging.error(f"❌ LLM error: {error_msg}", exc_info=True)
            await tts_queue.put(None)  # Signal TTS to stop
            await send({
                "jsonrpc": "2.0",
                "error": {
                    "code": 4,
                    "message": error_msg
                },
                "id": msg.get("id")
            })

    async def run_tts() -> None:
        nonlocal error_occurred
        try:
            tts_chunk_count = 0
            while True:
                block = await tts_queue.get()
                if block is None:
                    break

                tts_chunk_count += 1
                narrate_logger.info("🎤 Sending to TTS #%d (%d chars): %s", tts_chunk_count, len(block), repr(block))

                # Accumulate all audio chunks for this text block into a single MP3
                audio_buffer = bytearray()
                audio_fragment_count = 0
                tts_params = {
                    "text_block": block,
                    "api_key": session.api_key,
                    "voice": session.voice,
                    "instructions": character.tts_instructions,
                }
                if session.base_url:
                    tts_params["base_url"] = session.base_url
                if session.default_headers:
                    tts_params["default_headers"] = session.default_headers
                async for audio_chunk in stream_tts(**tts_params):
                    audio_fragment_count += 1
                    audio_buffer.extend(audio_chunk)
                    narrate_logger.debug("   🎵 Audio fragment #%d: %d bytes", audio_fragment_count, len(audio_chunk))

                # Send complete MP3 file as one event
                if audio_buffer:
                    narrate_logger.info("   ✅ Complete MP3 #%d: %d bytes (from %d fragments)",
                                       tts_chunk_count, len(audio_buffer), audio_fragment_count)
                    await send_audio_event(send, bytes(audio_buffer), encoding="hex")
        except openai.RateLimitError as e:
            error_occurred = True
            error_msg = f"OpenAI TTS API rate limit exceeded: {str(e)}"
            narrate_logger.error(f"❌ TTS rate limit error: {error_msg}")
            logging.error(f"❌ TTS rate limit error: {error_msg}")
            await send({
                "jsonrpc": "2.0",
                "error": {
                    "code": 5,
                    "message": error_msg
                },
                "id": msg.get("id")
            })
        except openai.APIError as e:
            error_occurred = True
            error_msg = f"OpenAI TTS API error: {str(e)}"
            narrate_logger.error(f"❌ TTS API error: {error_msg}")
            logging.error(f"❌ TTS API error: {error_msg}")
            await send({
                "jsonrpc": "2.0",
                "error": {
                    "code": 5,
                    "message": error_msg
                },
                "id": msg.get("id")
            })
        except Exception as e:
            error_occurred = True
            error_msg = f"TTS error: {str(e)}"
            narrate_logger.error(f"❌ TTS error: {error_msg}", exc_info=True)
            logging.error(f"❌ TTS error: {error_msg}", exc_info=True)
            await send({
                "jsonrpc": "2.0",
                "error": {
                    "code": 5,
                    "message": error_msg
                },
                "id": msg.get("id")
            })

    try:
        await asyncio.gather(run_llm(), run_tts())
        # Only send success response if no error was sent
        if not error_occurred:
            narrate_logger.info("✅ Narration complete, sending result response with id=%s", msg.get("id"))
            await send({"jsonrpc": "2.0", "result": "done", "id": msg.get("id")})
            narrate_logger.info("✅ Result response sent")
    except Exception as e:
        # This catches any errors in the gather itself
        if not error_occurred:
            error_msg = f"Narration error: {str(e)}"
            narrate_logger.error(f"❌ Narration error: {error_msg}", exc_info=True)
            logging.error(f"❌ Narration error: {error_msg}", exc_info=True)
            await send({
                "jsonrpc": "2.0",
                "error": {
                    "code": 6,
                    "message": error_msg
                },
                "id": msg.get("id")
            })


async def handle_initialize(msg: Dict[str, Any]) -> None:
    """Handle MCP initialize request."""
    await send({
        "jsonrpc": "2.0",
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "serverInfo": {
                "name": "narrator-mcp",
                "version": "1.0.0"
            }
        },
        "id": msg.get("id")
    })


async def handle_message(msg: Dict[str, Any]) -> None:
    method = msg.get("method")

    # Handle MCP protocol messages
    if method == "initialize":
        await handle_initialize(msg)
        return
    if method == "notifications/initialized":
        # Just acknowledge, no response needed
        logging.info("✅ Client sent initialized notification")
        return

    # Handle narrator-specific methods
    if method == "config":
        await handle_config(msg)
        return
    if method == "narrate":
        await handle_narrate(msg)
        return

    # Unknown method
    logging.warning(f"⚠️ Unknown method: {method}")
    await send(
        {
            "jsonrpc": "2.0",
            "error": {"code": -32601, "message": f"Unknown method '{method}'."},
            "id": msg.get("id"),
        }
    )


async def main() -> None:
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break

        stripped = line.strip()
        if not stripped:
            continue

        try:
            message = json.loads(stripped)
        except json.JSONDecodeError:
            await send(
                {
                    "jsonrpc": "2.0",
                    "error": {"code": -32700, "message": "Invalid JSON payload."},
                    "id": None,
                }
            )
            continue

        await handle_message(message)


if __name__ == "__main__":
    logging.info("🚀 Narration MCP Server starting (STDIO mode)...")
    logging.info("📝 Narrate logs will be written to: %s", narrate_log_file)
    asyncio.run(main())


__all__ = ["main"]
