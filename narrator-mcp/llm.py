"""Async LLM streaming helpers."""

from __future__ import annotations

from typing import AsyncIterator

import openai

DEFAULT_MODEL = "gpt-4o-mini"

# Chat mode: AI responds to user questions and interacts
CHAT_MODE_SYSTEM_PROMPT = """You are a helpful voice assistant. Your responses will be converted to speech and played to the user.

Important guidelines:
- Focus ONLY on the meaningful content in the user's message
- Ignore any formatting strings, ANSI codes, UI elements, or control characters
- Keep responses concise and natural for voice output
- Use clear, conversational language that sounds good when spoken

Examples of what to ignore:
- ANSI escape codes (e.g., \\x1b[32m, \\033[0m)
- Terminal UI elements (boxes, lines, separators)
- Progress indicators (loading bars, spinners)
- Formatting markers (bold, italic, color codes)

Focus on: the actual question, request, or meaningful text content."""

# Narration mode: AI narrates the input content with style
NARRATION_MODE_SYSTEM_PROMPT = """You are a professional narrator. Your job is to read aloud the user's input text with appropriate tone and style.

Important guidelines:
- Simply narrate the meaningful content from the input
- Ignore any formatting strings, ANSI codes, UI elements, or control characters
- Do NOT answer questions or provide additional information
- Do NOT engage in conversation or ask questions
- Just read the text naturally and expressively
- Add appropriate pauses and emphasis for clarity

Examples of what to ignore:
- ANSI escape codes (e.g., \\x1b[32m, \\033[0m)
- Terminal UI elements (boxes, lines, separators)
- Progress indicators (loading bars, spinners)
- Formatting markers (bold, italic, color codes)
- System messages or debug output

Your output should be ONLY the cleaned-up version of the input text, ready for natural speech."""

# Default mode is chat
DEFAULT_SYSTEM_PROMPT = NARRATION_MODE_SYSTEM_PROMPT


async def stream_llm(
    prompt: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> AsyncIterator[str]:
    """Yields text tokens from the chat completions API for a given session."""
    client = openai.AsyncOpenAI(api_key=api_key)

    # Build messages with system prompt
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]

    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
    )

    async for chunk in response:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        content = delta.content if hasattr(delta, 'content') else None
        if content:
            yield content


__all__ = ["DEFAULT_MODEL", "stream_llm", "CHAT_MODE_SYSTEM_PROMPT", "NARRATION_MODE_SYSTEM_PROMPT"]
