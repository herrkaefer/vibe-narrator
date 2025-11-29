#!/usr/bin/env python3
"""Play audio from narrate tool result."""

import base64
import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from audio_player import AudioPlayer
import time

def play_narrate_result(result_data):
    """Play audio from narrate tool result.

    Args:
        result_data: Can be:
            - A dict with 'audio' and 'text' keys
            - A JSON string
            - Base64 audio string
    """
    # Parse input
    if isinstance(result_data, str):
        try:
            data = json.loads(result_data)
        except json.JSONDecodeError:
            # Assume it's base64 audio
            audio_base64 = result_data
            text = ""
    else:
        data = result_data
        audio_base64 = data.get("audio", "")
        text = data.get("text", "")

    if not audio_base64:
        print("❌ No audio data found in result")
        return False

    print(f"📝 Text: {text}")
    print(f"🎵 Decoding audio (base64 length: {len(audio_base64)})...")

    try:
        audio_bytes = base64.b64decode(audio_base64)
        print(f"✅ Decoded {len(audio_bytes)} bytes of audio")
    except Exception as e:
        print(f"❌ Failed to decode audio: {e}")
        return False

    # Initialize and start audio player
    player = AudioPlayer()

    if not player.pyaudio_available:
        print("❌ PyAudio is not available!")
        return False

    print("🔊 Starting audio player...")
    player.start()

    if not player.is_playing:
        print("❌ Failed to start audio player")
        return False

    print("▶️  Playing audio...")
    player.add_chunk(audio_bytes)

    # Wait for playback to complete
    player.wait_for_completion(timeout=30)

    player.stop()
    print("✅ Playback complete")

    return True

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Read from command line argument (JSON string)
        result_data = sys.argv[1]
    else:
        # Read from stdin
        result_data = sys.stdin.read()

    success = play_narrate_result(result_data)
    sys.exit(0 if success else 1)



