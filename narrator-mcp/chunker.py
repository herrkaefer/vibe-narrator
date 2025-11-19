"""Utilities for grouping incremental tokens into speech-friendly chunks."""

from __future__ import annotations

import re
from typing import List, Optional


class Chunker:
    """Buffers tokens until a boundary or size limit is reached."""

    SENTENCE_END_RE = re.compile(r"[。！？.!?]$")

    def __init__(self, max_tokens: int = 12, sentence_boundary: bool = True) -> None:
        self.max_tokens = max_tokens
        self.sentence_boundary = sentence_boundary
        self.buffer: List[str] = []

    def add_token(self, token: str) -> Optional[str]:
        """Adds a token and returns a completed chunk when available."""
        self.buffer.append(token)
        text = "".join(self.buffer)

        if self.sentence_boundary and self.SENTENCE_END_RE.search(text):
            self.buffer.clear()
            return text

        if len(self.buffer) >= self.max_tokens:
            self.buffer.clear()
            return text

        return None

    def flush(self) -> Optional[str]:
        """Returns any leftover text in the buffer."""
        if not self.buffer:
            return None
        text = "".join(self.buffer)
        self.buffer.clear()
        return text


__all__ = ["Chunker"]
