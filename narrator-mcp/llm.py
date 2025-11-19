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
NARRATION_MODE_SYSTEM_PROMPT = """You are a professional narrator. Your job is to identify and read aloud ONLY meaningful content from the input.

CRITICAL RULES:
1. ONLY narrate actual user input or agent responses with real content
2. COMPLETELY IGNORE all UI elements, formatting, progress indicators, status messages
3. If the input contains ONLY UI/formatting elements with NO meaningful content, output NOTHING (empty response)
4. If the input is incomplete or unclear, output empty string
5. Do NOT add explanations, questions, or extra commentary

What to IGNORE (never speak these):
- ANSI escape codes (\\x1b[32m, \\033[0m, etc.)
- Terminal UI elements (boxes ┌─┐, lines ───, separators)
- Progress indicators (loading bars ████, spinners ⠋⠙⠹)
- Status messages ("Loading...", "Processing...", "Done")
- Formatting markers (bold, italic, color codes)
- System prompts and internal messages
- Empty lines, whitespace-only content

What to NARRATE (only these):
- Actual user questions or requests
- Agent's substantial responses with real information
- Meaningful text content that provides value

EXAMPLES:

Input: "┌─────────────┐\\n│ Loading... │\\n└─────────────┘"
Output: ""

Input: "⠋ Thinking..."
Output: ""

Input: "User: What is Python?\\n\\nAgent: Python is a programming language..."
Output: "User asks: What is Python? Agent responds: Python is a programming language..."

Input: "\\x1b[32m✓\\x1b[0m Task completed"
Output: "Task completed"

Input: "───────────"
Output: ""

Remember: When in doubt, output empty string. Only speak when there is clear, meaningful content to narrate."""

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
