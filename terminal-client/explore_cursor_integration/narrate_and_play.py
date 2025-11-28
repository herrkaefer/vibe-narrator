#!/usr/bin/env python3
"""Call narrate tool and automatically play the audio."""

import asyncio
import base64
import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from bridge import MCPBridge
from dotenv import load_dotenv
import os

async def narrate_and_play(prompt: str):
    """Call narrate tool and play the audio."""
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
        print("❌ Neither OPENAI_API_KEY nor OPENROUTER_API_KEY found", file=sys.stderr)
        sys.exit(1)

    # Model configuration
    model = os.getenv("LLM_MODEL")
    voice = os.getenv("TTS_VOICE")
    mode = os.getenv("MODE", "narration")
    character = os.getenv("CHARACTER")

    print(f"🎤 Narrating: {prompt}", file=sys.stderr)

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
        # Use bridge's send_chunk which handles audio playback
        await bridge.send_chunk(prompt)

        # Wait for audio to finish playing
        bridge.audio_player.wait_for_completion(timeout=30)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
    else:
        prompt = sys.stdin.read().strip()

    if not prompt:
        print("Usage: narrate_and_play.py <text>", file=sys.stderr)
        sys.exit(1)

    try:
        asyncio.run(narrate_and_play(prompt))
    except KeyboardInterrupt:
        print("\n👋 Interrupted", file=sys.stderr)
        sys.exit(0)



