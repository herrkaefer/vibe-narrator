"""Session state for the stdin/stdout MCP server."""

from __future__ import annotations

from typing import Optional

from characters import DEFAULT_CHARACTER_ID

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_VOICE = "nova"
DEFAULT_MODE = "narration"  # "chat" or "narration"


class Session:
    """Represents the currently active MCP session (process-local)."""

    def __init__(self) -> None:
        self.llm_api_key: Optional[str] = None
        self.llm_model: str = DEFAULT_MODEL
        self.voice: str = DEFAULT_VOICE
        self.mode: str = DEFAULT_MODE  # "chat" or "narration"
        self.character: Optional[str] = None  # character ID, defaults to DEFAULT_CHARACTER_ID if None
        self.base_url: Optional[str] = None  # Optional base URL for API (e.g., OpenRouter)
        self.default_headers: Optional[dict] = None  # Optional headers (e.g., for OpenRouter)
        self.tts_api_key: Optional[str] = None  # TTS-specific API key (for OpenAI or ElevenLabs TTS)
        self.tts_provider: Optional[str] = None  # TTS provider: "openai" or "elevenlabs" (auto-detected if None)


__all__ = ["Session", "DEFAULT_MODEL", "DEFAULT_VOICE", "DEFAULT_MODE"]
