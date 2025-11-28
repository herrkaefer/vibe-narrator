#!/usr/bin/env python3
"""Test audio playback functionality."""

import base64
import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from audio_player import AudioPlayer
import time

def test_audio_playback():
    """Test if audio player can play audio."""
    print("🔊 Testing audio playback...")

    player = AudioPlayer()

    if not player.pyaudio_available:
        print("❌ PyAudio is not available!")
        print("   Please install PyAudio: pip install pyaudio")
        return False

    print("✅ PyAudio is available")

    # Start the player
    player.start()

    if not player.is_playing:
        print("❌ Audio player failed to start!")
        return False

    print("✅ Audio player started")

    # Test with a simple audio file or base64 data
    # For now, just check if it's ready
    print("✅ Audio player is ready to play")
    print("   You can now test with actual audio data")

    # Keep it running for a bit
    time.sleep(1)

    player.stop()
    print("✅ Audio player stopped")

    return True

if __name__ == "__main__":
    success = test_audio_playback()
    sys.exit(0 if success else 1)



