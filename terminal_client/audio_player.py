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

    # Audio buffer configuration - larger buffers reduce underrun risk on slower machines
    FRAMES_PER_BUFFER = 4096  # Increased from default 1024 to reduce buffer underrun
    FADE_MS = 5  # Milliseconds of fade in/out to reduce pops between chunks

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

        # Skip empty audio data
        if not mp3_data or len(mp3_data) == 0:
            logger.debug("⏭️ Skipping empty audio chunk")
            return

        self.audio_queue.put(mp3_data)
        logger.debug(f"Added audio chunk to queue ({len(mp3_data)} bytes)")

    def _playback_worker(self):
        """Worker thread that plays audio chunks."""
        try:
            from pydub import AudioSegment
        except ImportError:
            logger.error("❌ pydub not available - cannot play audio")
            return

        # Initialize persistent PyAudio stream
        p = None
        stream = None
        current_format = None
        current_channels = None
        current_rate = None

        try:
            logger.info("🎧 Audio playback worker started")
            p = self.pyaudio.PyAudio()

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

                        # Apply fade in/out to reduce pops between chunks
                        if len(audio) > self.FADE_MS * 2:
                            audio = audio.fade_in(self.FADE_MS).fade_out(self.FADE_MS)

                        # Check if we need to recreate the stream (format changed)
                        if (stream is None or
                            current_format != p.get_format_from_width(audio.sample_width) or
                            current_channels != audio.channels or
                            current_rate != audio.frame_rate):

                            # Close old stream if exists
                            if stream is not None:
                                stream.stop_stream()
                                stream.close()

                            # Create new stream with current audio format
                            current_format = p.get_format_from_width(audio.sample_width)
                            current_channels = audio.channels
                            current_rate = audio.frame_rate

                            stream = p.open(
                                format=current_format,
                                channels=current_channels,
                                rate=current_rate,
                                output=True,
                                frames_per_buffer=self.FRAMES_PER_BUFFER
                            )
                            logger.debug(f"🎚️  Opened audio stream: {current_rate}Hz, {current_channels}ch, buffer={self.FRAMES_PER_BUFFER}")

                        # Write audio data to stream
                        stream.write(audio.raw_data)

                    except Exception as e:
                        logger.error(f"❌ Error playing audio chunk: {e}")

                    self.audio_queue.task_done()

                except queue.Empty:
                    continue

        except Exception as e:
            logger.exception(f"❌ Audio playback worker error: {e}")
        finally:
            # Cleanup
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except:
                    pass
            if p is not None:
                try:
                    p.terminate()
                except:
                    pass
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
            logger.debug("Sent stop sentinel to audio queue")

        # Wait for playback thread to finish
        if self.playback_thread and self.playback_thread.is_alive():
            logger.debug("Waiting for playback thread to finish...")
            self.playback_thread.join(timeout=2.0)
            if self.playback_thread.is_alive():
                logger.warning("⚠️ Playback thread did not finish within 2 seconds")
            else:
                logger.debug("Playback thread finished")

        logger.info("✅ Audio playback stopped")

    def wait_for_completion(self, timeout: Optional[float] = None):
        """Wait for all queued audio to finish playing."""
        if not self.pyaudio_available:
            return

        logger.info("⏳ Waiting for audio playback to complete...")
        try:
            import time
            start = time.time()

            # Wait for queue to be processed (all task_done() called)
            while True:
                # Check if queue is empty and all tasks are done
                if self.audio_queue.unfinished_tasks == 0:
                    break

                # Check timeout
                if timeout is not None and (time.time() - start) >= timeout:
                    logger.warning(f"⚠️ Audio playback timeout after {timeout}s")
                    break

                time.sleep(0.1)
        except Exception as e:
            logger.debug(f"Error waiting for audio completion: {e}")

        logger.info("✅ Audio playback completed")

    def get_queue_size(self) -> int:
        """Get the number of chunks waiting to be played."""
        return self.audio_queue.qsize()


__all__ = ["AudioPlayer"]
