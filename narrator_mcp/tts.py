"""Async TTS streaming helpers."""

from __future__ import annotations

import json
from typing import AsyncIterator, Optional

import httpx
import openai

DEFAULT_TTS_MODEL = "gpt-4o-mini-tts"
DEFAULT_TTS_VOICE = "nova"
DEFAULT_ELEVENLABS_MODEL = "eleven_turbo_v2_5"
TTS_FORMAT = "mp3"
ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"


def detect_tts_provider(api_key: str) -> str:
    """
    Best-effort TTS provider detection.
    Defaults to OpenAI unless a known ElevenLabs prefix is found.
    """
    lowered = api_key.lower()
    if lowered.startswith("elevenlabs_") or lowered.startswith("el-"):
        return "elevenlabs"
    return "openai"


async def stream_tts(
    text_block: str,
    api_key: str,
    voice: str = DEFAULT_TTS_VOICE,
    model: str = DEFAULT_TTS_MODEL,
    instructions: Optional[str] = None,
    base_url: Optional[str] = None,
    default_headers: Optional[dict] = None,
    tts_provider: Optional[str] = None,
) -> AsyncIterator[bytes]:
    """
    Yields audio bytes for the provided chunk of text.

    Supports both OpenAI and ElevenLabs TTS providers.
    Provider is auto-detected from API key format if not explicitly specified.
    """
    # Auto-detect provider if not specified
    if tts_provider is None:
        tts_provider = detect_tts_provider(api_key)

    if tts_provider == "elevenlabs":
        async for chunk in _stream_elevenlabs_tts(
            text_block=text_block,
            api_key=api_key,
            voice_id=voice,
            model=model if model != DEFAULT_TTS_MODEL else DEFAULT_ELEVENLABS_MODEL,
            instructions=instructions,
        ):
            yield chunk
    else:  # openai (default)
        async for chunk in _stream_openai_tts(
            text_block=text_block,
            api_key=api_key,
            voice=voice,
            model=model,
            instructions=instructions,
            base_url=base_url,
            default_headers=default_headers,
        ):
            yield chunk


async def _stream_openai_tts(
    text_block: str,
    api_key: str,
    voice: str,
    model: str,
    instructions: Optional[str] = None,
    base_url: Optional[str] = None,
    default_headers: Optional[dict] = None,
) -> AsyncIterator[bytes]:
    """Stream TTS audio from OpenAI."""
    # Set timeout to prevent indefinite blocking - TTS can take a while for longer text
    # Using 60s total timeout with 30s connect timeout
    timeout_config = httpx.Timeout(60.0, connect=30.0)

    client_kwargs = {
        "api_key": api_key,
        "timeout": timeout_config,
    }
    if base_url:
        client_kwargs["base_url"] = base_url
    if default_headers:
        client_kwargs["default_headers"] = default_headers
    client = openai.AsyncOpenAI(**client_kwargs)
    create_params = {
        "model": model,
        "voice": voice,
        "input": text_block,
        "response_format": TTS_FORMAT,
    }
    if instructions:
        create_params["instructions"] = instructions
    response = await client.audio.speech.create(**create_params)

    # OpenAI audio.speech returns HttpxBinaryResponseContent
    # We need to read the content and yield it in chunks
    for chunk in response.iter_bytes(chunk_size=4096):
        if chunk:
            yield chunk


async def _stream_elevenlabs_tts(
    text_block: str,
    api_key: str,
    voice_id: str,
    model: str = DEFAULT_ELEVENLABS_MODEL,
    instructions: Optional[str] = None,
) -> AsyncIterator[bytes]:
    """
    Stream TTS audio from ElevenLabs.

    ElevenLabs models interpret emotional context from text naturally.
    Character instructions can be incorporated into the text for emotional expression.
    """
    # Prepare text - ElevenLabs models interpret emotional cues from text
    text = text_block

    # Build request payload
    url = f"{ELEVENLABS_API_BASE}/text-to-speech/{voice_id}"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": api_key,
    }

    payload = {
        "text": text,
        "model_id": model,
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
        },
    }

    # Make streaming request
    async with httpx.AsyncClient(timeout=30.0) as client:
        async with client.stream(
            "POST",
            url,
            headers=headers,
            json=payload,
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes(chunk_size=4096):
                if chunk:
                    yield chunk


__all__ = [
    "DEFAULT_TTS_MODEL",
    "DEFAULT_TTS_VOICE",
    "DEFAULT_ELEVENLABS_MODEL",
    "stream_tts",
    "detect_tts_provider",
]
