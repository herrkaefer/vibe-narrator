"""Async TTS streaming helpers."""

from __future__ import annotations

from typing import AsyncIterator

import openai

DEFAULT_TTS_MODEL = "gpt-4o-mini-tts"
DEFAULT_TTS_VOICE = "alloy"
TTS_FORMAT = "mp3"


async def stream_tts(
    text_block: str,
    api_key: str,
    voice: str = DEFAULT_TTS_VOICE,
    model: str = DEFAULT_TTS_MODEL,
) -> AsyncIterator[bytes]:
    """Yields audio bytes for the provided chunk of text using the session key."""
    client = openai.AsyncOpenAI(api_key=api_key)
    response = await client.audio.speech.create(
        model=model,
        voice=voice,
        input=text_block,
        response_format=TTS_FORMAT,
    )

    # OpenAI audio.speech returns HttpxBinaryResponseContent
    # We need to read the content and yield it in chunks
    for chunk in response.iter_bytes(chunk_size=4096):
        if chunk:
            yield chunk


__all__ = ["DEFAULT_TTS_MODEL", "DEFAULT_TTS_VOICE", "stream_tts"]
