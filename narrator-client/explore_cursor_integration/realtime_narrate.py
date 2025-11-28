#!/usr/bin/env python3
"""Real-time narration mode for AI assistant output.

This script reads text from stdin and sends it to narrator-mcp for real-time narration.
It buffers text intelligently and sends chunks for narration as they become available.
"""

import asyncio
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
import os

from bridge import MCPBridge, clean_text, TextBuffer


async def realtime_narrate():
    """Read from stdin and narrate in real-time."""
    # Load environment variables
    client_dir = Path(__file__).parent.absolute()
    project_root = client_dir.parent

    env_file = client_dir / ".env"
    if not env_file.exists():
        env_file = project_root / ".env"

    if env_file.exists():
        load_dotenv(env_file)

    # Get API configuration
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    tts_api_key = os.getenv("TTS_API_KEY")
    tts_provider = os.getenv("TTS_PROVIDER")

    base_url = None
    default_headers = None
    api_key = None

    # TTS API key: prefer TTS_API_KEY, fallback to OPENAI_API_KEY
    if tts_api_key:
        pass  # Use TTS_API_KEY
    elif openai_api_key:
        tts_api_key = openai_api_key
    else:
        print("❌ TTS requires API key", file=sys.stderr)
        print("Please set either TTS_API_KEY or OPENAI_API_KEY in .env file", file=sys.stderr)
        sys.exit(1)

    if openrouter_api_key:
        api_key = openrouter_api_key
        base_url = "https://openrouter.ai/api/v1"
        default_headers = {
            "HTTP-Referer": os.getenv("OPENROUTER_REFERER", "https://github.com/herrkaefer/vibe-narrator"),
            "X-Title": os.getenv("OPENROUTER_TITLE", "Vibe Narrator"),
        }
    elif openai_api_key:
        api_key = openai_api_key
        custom_base_url = os.getenv("OPENAI_BASE_URL")
        if custom_base_url:
            base_url = custom_base_url
    else:
        print("❌ Neither OPENAI_API_KEY nor OPENROUTER_API_KEY found in environment", file=sys.stderr)
        print("Please create a .env file with your API key", file=sys.stderr)
        sys.exit(1)

    # Model configuration
    model = os.getenv("LLM_MODEL")
    voice = os.getenv("TTS_VOICE")
    mode = os.getenv("MODE", "narration")  # Default to narration mode for real-time
    character = os.getenv("CHARACTER")

    # Text buffer for intelligent chunking
    text_buffer = TextBuffer(min_window_seconds=2.0, pause_threshold=3.0)

    print("🎤 Real-time narration mode started", file=sys.stderr)
    print("📝 Reading from stdin, sending to narrator-mcp...", file=sys.stderr)
    print("Press Ctrl+D or Ctrl+C to exit", file=sys.stderr)
    print("", file=sys.stderr)

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
        use_stdio=False
    ) as bridge:
        loop = asyncio.get_event_loop()

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

                # Read from stdin (non-blocking)
                try:
                    # Use asyncio to read from stdin
                    line = await asyncio.wait_for(
                        loop.run_in_executor(None, sys.stdin.readline),
                        timeout=0.1
                    )

                    if not line:
                        # EOF reached
                        break

                    # Add to buffer
                    text_buffer.add_data(line, current_time)

                except asyncio.TimeoutError:
                    # No input available, continue to check buffer
                    continue
                except Exception as e:
                    print(f"❌ Error reading input: {e}", file=sys.stderr)
                    break

            # Flush remaining buffer
            remaining = text_buffer.flush_all()
            if remaining:
                clean = clean_text(remaining)
                if clean:
                    await bridge.send_chunk(clean)

        except KeyboardInterrupt:
            print("\n⚠️ Interrupted by user", file=sys.stderr)
            # Flush remaining buffer
            remaining = text_buffer.flush_all()
            if remaining:
                clean = clean_text(remaining)
                if clean:
                    await bridge.send_chunk(clean)


if __name__ == "__main__":
    try:
        asyncio.run(realtime_narrate())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!", file=sys.stderr)
        sys.exit(0)



