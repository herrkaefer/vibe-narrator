"""Session state for the stdin/stdout MCP server."""

from __future__ import annotations

from typing import Optional

from characters import DEFAULT_CHARACTER_ID

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_VOICE = "alloy"
DEFAULT_MODE = "chat"  # "chat" or "narration"


class Session:
    """Represents the currently active MCP session (process-local)."""

    def __init__(self) -> None:
        self.api_key: Optional[str] = None
        self.model: str = DEFAULT_MODEL
        self.voice: str = DEFAULT_VOICE
        self.mode: str = DEFAULT_MODE  # "chat" or "narration"
        self.character: Optional[str] = None  # character ID, defaults to DEFAULT_CHARACTER_ID if None
        self.base_url: Optional[str] = None  # Optional base URL for API (e.g., OpenRouter)
        self.default_headers: Optional[dict] = None  # Optional headers (e.g., for OpenRouter)
        self.tts_api_key: Optional[str] = None  # TTS-specific API key (for OpenAI TTS)


__all__ = ["Session", "DEFAULT_MODEL", "DEFAULT_VOICE", "DEFAULT_MODE"]
