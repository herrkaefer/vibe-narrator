"""Cross-platform streaming audio player for MP3 data."""

import io
import logging
import queue
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class AudioPlayer:
    """
    Streaming audio player that can play MP3 chunks as they arrive.

    Supports:
    - macOS (via PyAudio + pydub)
    - Linux (via PyAudio + pydub)
    - Windows (via PyAudio + pydub)
    """

    def __init__(self):
        self.audio_queue: queue.Queue = queue.Queue()
        self.is_playing = False
        self.playback_thread: Optional[threading.Thread] = None
        self.pyaudio_instance = None
        self.stream = None

        # Try to initialize PyAudio
        try:
            import pyaudio
            self.pyaudio = pyaudio
            self.pyaudio_available = True
            logger.info("🔊 PyAudio initialized successfully")
        except ImportError:
            self.pyaudio = None
            self.pyaudio_available = False
            logger.warning("⚠️  PyAudio not available - audio playback disabled")
        except Exception as e:
            self.pyaudio = None
            self.pyaudio_available = False
            logger.warning(f"⚠️  PyAudio initialization failed: {e}")

    def start(self):
        """Start the audio playback thread."""
        if not self.pyaudio_available:
            logger.info("🔇 Audio playback disabled (PyAudio not available)")
            return

        if self.is_playing:
            logger.warning("⚠️  Audio player already running")
            return

        self.is_playing = True
        self.playback_thread = threading.Thread(
            target=self._playback_worker,
            name="AudioPlayback",
            daemon=True
        )
        self.playback_thread.start()
        logger.info("🎵 Audio playback started")

    def add_chunk(self, mp3_data: bytes):
        """Add an MP3 chunk to the playback queue."""
        if not self.pyaudio_available:
            return

        if not self.is_playing:
            logger.warning("⚠️  Audio player not started, cannot add chunk")
            return

        self.audio_queue.put(mp3_data)
        logger.debug(f"Added audio chunk to queue ({len(mp3_data)} bytes)")

    def _playback_worker(self):
        """Worker thread that plays audio chunks."""
        try:
            from pydub import AudioSegment
            from pydub.playback import _play_with_pyaudio
        except ImportError:
            logger.error("❌ pydub not available - cannot play audio")
            return

        try:
            logger.info("🎧 Audio playback worker started")

            while self.is_playing:
                try:
                    # Get chunk from queue with timeout
                    mp3_data = self.audio_queue.get(timeout=0.5)

                    if mp3_data is None:  # Sentinel for stop
                        break

                    # Convert MP3 bytes to AudioSegment
                    try:
                        audio = AudioSegment.from_mp3(io.BytesIO(mp3_data))
                        logger.debug(f"Playing audio chunk: {len(audio)}ms, {audio.frame_rate}Hz")

                        # Play the audio
                        _play_with_pyaudio(audio)

                    except Exception as e:
                        logger.error(f"❌ Error playing audio chunk: {e}")

                    self.audio_queue.task_done()

                except queue.Empty:
                    continue

        except Exception as e:
            logger.exception(f"❌ Audio playback worker error: {e}")
        finally:
            logger.info("🎧 Audio playback worker stopped")

    def stop(self):
        """Stop audio playback and cleanup."""
        if not self.is_playing:
            return

        logger.info("🛑 Stopping audio playback...")
        self.is_playing = False

        # Send sentinel to stop worker
        if self.pyaudio_available:
            self.audio_queue.put(None)

        # Wait for playback thread to finish
        if self.playback_thread and self.playback_thread.is_alive():
            self.playback_thread.join(timeout=2.0)

        # Wait for queue to empty
        try:
            self.audio_queue.join()
        except:
            pass

        logger.info("✅ Audio playback stopped")

    def wait_for_completion(self, timeout: Optional[float] = None):
        """Wait for all queued audio to finish playing."""
        if not self.pyaudio_available:
            return

        logger.info("⏳ Waiting for audio playback to complete...")
        try:
            if timeout:
                self.audio_queue.join()
            else:
                # Wait with timeout
                import time
                start = time.time()
                while not self.audio_queue.empty() and (time.time() - start) < (timeout or 30):
                    time.sleep(0.1)
        except Exception as e:
            logger.debug(f"Error waiting for audio completion: {e}")

        logger.info("✅ Audio playback queue empty")

    def get_queue_size(self) -> int:
        """Get the number of chunks waiting to be played."""
        return self.audio_queue.qsize()


__all__ = ["AudioPlayer"]
