"""Async LLM streaming helpers."""

from __future__ import annotations

from typing import AsyncIterator

import openai

DEFAULT_MODEL = "gpt-4o-mini"


async def stream_llm(
    prompt: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
) -> AsyncIterator[str]:
    """Yields text tokens from the chat completions API for a given session."""
    client = openai.AsyncOpenAI(api_key=api_key)
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        stream=True,
    )

    async for chunk in response:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        content = delta.get("content")
        if content:
            yield content


__all__ = ["DEFAULT_MODEL", "stream_llm"]
