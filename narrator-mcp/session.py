"""Session state for the stdin/stdout MCP server."""

from __future__ import annotations

from typing import Optional

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_VOICE = "alloy"


class Session:
    """Represents the currently active MCP session (process-local)."""

    def __init__(self) -> None:
        self.api_key: Optional[str] = None
        self.model: str = DEFAULT_MODEL
        self.voice: str = DEFAULT_VOICE


__all__ = ["Session", "DEFAULT_MODEL", "DEFAULT_VOICE"]
