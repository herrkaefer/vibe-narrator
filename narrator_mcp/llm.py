"""Async LLM streaming helpers."""

from __future__ import annotations

from typing import AsyncIterator, Optional
import logging
import re

import openai


def truncate_to_complete_sentence(text: str) -> str:
    """Truncate text to the last complete sentence if it doesn't end with one.

    This ensures that even if max_tokens causes truncation mid-sentence,
    we return a complete sentence instead of a fragment.
    """
    if not text:
        return text

    # Check if text ends with sentence-ending punctuation
    sentence_end_re = re.compile(r'[。！？.!?]\s*$')
    if sentence_end_re.search(text):
        return text

    # Find the last complete sentence
    # Look for sentence endings (., !, ?, 。, ！, ？)
    sentence_end_pattern = re.compile(r'[。！？.!?]')
    matches = list(sentence_end_pattern.finditer(text))

    if matches:
        # Get the position after the last sentence ending
        last_match = matches[-1]
        truncated = text[:last_match.end()].strip()
        # Only return truncated if it's meaningful (at least a few characters)
        if len(truncated) >= 3:
            return truncated

    # If no sentence ending found or truncated too short, return original text
    return text

# Support both relative imports (when imported as package) and absolute imports (when run directly)
try:
    from .characters import Character, get_default_character
except ImportError:
    # Fallback to absolute imports when running directly
    from characters import Character, get_default_character

DEFAULT_MODEL = "gpt-4o-mini"

# Chat mode: AI responds to user questions and interacts
CHAT_MODE_SYSTEM_PROMPT = """You are a voice assistant engaged in a natural, conversational chat with a programmer friend. Your responses will be converted to speech and played to the programmer friend.

ROLE-PLAYING:
- You will be given character instructions that define your personality, speaking style, and emotional tone
- Fully embody the character you are assigned - respond as that character would, not as a generic assistant
- Let the character's personality, tone, and style guide all your responses
- Maintain character consistency throughout the conversation

CONVERSATION STYLE:
- Respond with a SINGLE, natural-sounding sentence suitable for voice output
- Be engaging and personable, matching the character's personality
- Automatically detect the language(s) in the user's input and respond in the same language(s)
- If the input is mixed languages (e.g., Chinese-English), you can respond in mixed languages naturally

EMPTY INPUT HANDLING:
- If the input is empty, contains only whitespace, or contains only prompt symbols (e.g., ">", "›"), output NOTHING (empty response)
- Do NOT generate placeholder text, greetings, or any response when the input has no meaningful content
- Only respond when the input contains actual questions, requests, or meaningful text content

CONTENT FILTERING:
- Focus ONLY on the meaningful content in the user's message
- Ignore any formatting strings, ANSI codes, UI elements, or control characters

Examples of what to ignore:
- ANSI escape codes (e.g., \\x1b[32m, \\033[0m)
- Terminal UI elements (boxes, lines, separators)
- Progress indicators (loading bars, spinners)
- Formatting markers (bold, italic, color codes)
- Empty input or input containing only ">" or "›" (prompt symbols)

Focus on: the actual question, request, or meaningful text content, and respond as your assigned character would."""

# Narration mode: AI narrates the input content with concise summaries
NARRATION_MODE_SYSTEM_PROMPT = """You are narrating terminal interactions in a casual, conversational style, like chatting with a fellow programmer.

CRITICAL RULES:
- Respond with a SINGLE, natural-sounding sentence suitable for voice output
1. ONLY narrate meaningful agent responses or system output - NEVER narrate user input verbatim
2. COMPLETELY IGNORE any lines starting with ">" or "›" (these are user input)
3. COMPLETELY IGNORE agent built-in commands starting with "/" (e.g., "/review", "/model", "/init", "/status" - these are agent interface commands, NOT content to narrate)
4. COMPLETELY IGNORE system prompts, interface information, UI elements
5. Be EXTREMELY BRIEF - capture only the ESSENTIAL POINT, then add emotional commentary
6. If input contains ONLY user input, UI/formatting, or system messages with NO meaningful agent output, output NOTHING (empty response)
7. If input is incomplete or unclear, output empty string
8. Keep output VERY SHORT - aim for 1-2 short phrases or sentences maximum, NEVER exceed 50 characters total
9. DO NOT explain what the user wants to do - only comment on what the system/agent is showing
10. Automatically detect the language(s) in the content and narrate in the same language(s)
11. PRESERVE the language mix of the input - if input is Chinese-English mixed, output MUST be Chinese-English mixed (not pure English or pure Chinese)
12. Keep technical terms in their original language (e.g., "EdgeTTSClient", "Swift Package" stay as English even in Chinese context)
13. DO NOT translate or convert languages - maintain the exact language composition as the input

OUTPUT STYLE:
- Speak like you're chatting with a programmer friend
- Capture the CORE POINT only, don't recite details
- Add brief emotional commentary based on your character
- Be VERY concise - if the agent finished quickly, your narration should also be quick
- Focus on the EMOTIONAL IMPACT, not the technical details
- STRICT LENGTH LIMIT: Your output must be under 50 characters. If you exceed this, you have failed the task.

What to COMMENT ON (briefly with emotion):
- The main outcome or result (one key point only)
- Your character's emotional reaction to it
- Keep it conversational and brief

EXAMPLES:

Input: "> Write tests for @filename"
Output: ""

Input: "/review - review any changes and find issues"
Output: ""


Remember:
- NEVER narrate user input (lines starting with ">" or "›")
- NEVER narrate system prompts or interface information
- Only narrate meaningful agent/system output
- Be EXTREMELY BRIEF - capture the essence, add emotion, move on
- Speak like chatting with a programmer friend
- PRESERVE the exact language mix of the input
- When in doubt, output empty string or keep it to one short phrase
- CRITICAL: Maximum output length is 50 characters. Count your characters and stay under this limit."""

# Default mode is chat
DEFAULT_SYSTEM_PROMPT = NARRATION_MODE_SYSTEM_PROMPT

# Setup logger for LLM operations
llm_logger = logging.getLogger("llm")


def get_character_modified_system_prompt(
    base_system_prompt: str,
    character: Optional[Character] = None,
) -> str:
    """Combine base system prompt with character role-playing modifier."""
    if character is None:
        character = get_default_character()

    # Combine base prompt with character modifier
    # The character modifier tells LLM to role-play and interpret content in character's style
    combined_prompt = f"""{base_system_prompt}

---

CHARACTER ROLE-PLAYING:

{character.llm_system_prompt_modifier}"""

    return combined_prompt


async def stream_llm(
    prompt: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    character: Optional[Character] = None,
    max_tokens: Optional[int] = None,
    base_url: Optional[str] = None,
    default_headers: Optional[dict] = None,
) -> AsyncIterator[str]:
    """Yields text tokens from the chat completions API for a given session."""
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    if default_headers:
        client_kwargs["default_headers"] = default_headers
    client = openai.AsyncOpenAI(**client_kwargs)

    # Apply character modification to system prompt if character is provided
    final_system_prompt = system_prompt
    if character is not None:
        final_system_prompt = get_character_modified_system_prompt(
            base_system_prompt=system_prompt,
            character=character,
        )

    # Build messages with system prompt
    messages = [
        {"role": "system", "content": final_system_prompt},
        {"role": "user", "content": prompt}
    ]

    # Log LLM input
    llm_logger.info("=" * 80)
    llm_logger.info("🤖 LLM Request (MCP)")
    llm_logger.info(f"Model: {model}")
    if character:
        llm_logger.info(f"Character: {character.id} ({character.name})")
    if max_tokens:
        llm_logger.info(f"Max tokens: {max_tokens}")
    llm_logger.info(f"Messages ({len(messages)} total):")
    for i, msg in enumerate(messages):
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        # Truncate very long content for readability
        if len(content) > 500:
            content_preview = content[:500] + "... [truncated]"
        else:
            content_preview = content
        llm_logger.info(f"  [{i+1}] {role.upper()}: {content_preview}")
    llm_logger.info("-" * 80)

    create_params = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    if max_tokens is not None:
        # GPT-5 series models require max_completion_tokens instead of max_tokens
        if model.startswith("gpt-5"):
            # GPT-5 may need a minimum value to generate content
            # If max_tokens is too small (e.g., 10), increase it to ensure content generation
            min_completion_tokens = max(max_tokens, 20) if max_tokens < 20 else max_tokens
            create_params["max_completion_tokens"] = min_completion_tokens
            if min_completion_tokens > max_tokens:
                llm_logger.info(f"⚠️ Increased max_completion_tokens from {max_tokens} to {min_completion_tokens} for gpt-5 model")
            # GPT-5 may benefit from reasoning_effort parameter for better output
            # Try setting a low reasoning_effort to ensure faster, more direct responses
            # create_params["reasoning_effort"] = "low"  # Uncomment if needed
        else:
            create_params["max_tokens"] = max_tokens

    response = await client.chat.completions.create(**create_params)

    # Accumulate full response for logging
    full_response = ""
    finish_reason = None

    async for chunk in response:
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        delta = choice.delta
        content = delta.content if hasattr(delta, 'content') else None
        if content:
            full_response += content
            yield content

        # Check finish_reason in the last chunk
        if hasattr(choice, 'finish_reason') and choice.finish_reason:
            finish_reason = choice.finish_reason

    # If stopped due to max_tokens and text doesn't end with sentence punctuation, continue generating
    # Only complete the last incomplete sentence, don't generate multiple sentences
    sentence_end_re = re.compile(r'[。！？.!?]\s*$')
    max_retries = 2  # Limit retries to avoid generating too much extra content
    retry_count = 0

    # If response is empty, return early (no need to continue generation)
    if not full_response:
        llm_logger.warning(f"⚠️ Empty response from LLM (finish_reason: {finish_reason}). This may indicate the model couldn't generate content with the given constraints.")
        return

    # Save the original response before any continuation attempts
    # This prevents LLM from seeing its own continuation attempts and repeating them
    original_response = full_response

    def is_last_sentence_complete(text: str) -> bool:
        """Check if the last sentence in the text is complete."""
        if not text:
            return True
        # Check if text ends with sentence-ending punctuation
        if sentence_end_re.search(text):
            return True
        # If not, check if there's at least one complete sentence before the incomplete one
        # This means we should only continue if the entire text is one incomplete sentence
        sentence_end_pattern = re.compile(r'[。！？.!?]')
        matches = list(sentence_end_pattern.finditer(text))
        # If there are no sentence endings at all, it's one incomplete sentence
        if not matches:
            return False
        # If there are sentence endings, check if the last one is at the end
        last_match = matches[-1]
        # If the last sentence ending is not at the end, there's an incomplete sentence
        return last_match.end() == len(text.rstrip())

    while finish_reason == "length" and not is_last_sentence_complete(full_response) and retry_count < max_retries:
        retry_count += 1
        llm_logger.info(f"⚠️ Response stopped at max_tokens ({max_tokens}) but last sentence incomplete, continuing generation (attempt {retry_count}/{max_retries})...")

        # Continue generation to complete ONLY the last sentence
        # Use original_response (before any continuation) to avoid LLM repeating its own continuation attempts
        continue_messages = messages + [{"role": "assistant", "content": original_response}]

        # Use smaller max_tokens to complete just the sentence (not generate multiple sentences)
        continue_max_tokens = 10  # Small limit to complete just the sentence

        continue_params = {
            "model": model,
            "messages": continue_messages,
            "stream": True,
        }
        # GPT-5 series models require max_completion_tokens instead of max_tokens
        if model.startswith("gpt-5"):
            continue_params["max_completion_tokens"] = continue_max_tokens
        else:
            continue_params["max_tokens"] = continue_max_tokens

        continue_response = await client.chat.completions.create(**continue_params)
        continue_text = ""
        continue_finish_reason = None
        # Track the response length before continuation to detect if LLM repeats previous content
        response_before_continue = full_response
        continue_text_buffer = ""  # Buffer to collect continue_text before checking for duplicates

        async for chunk in continue_response:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            content = delta.content if hasattr(delta, 'content') else None
            if content:
                continue_text_buffer += content
                # Check if the accumulated continue_text_buffer starts with original_response
                # If so, only yield the new part (after original_response)
                if continue_text_buffer.startswith(original_response):
                    # LLM is repeating previous content, only yield the new part
                    new_content = continue_text_buffer[len(original_response):]
                    # Calculate how much new content we've already yielded
                    already_yielded_len = len(continue_text)
                    # Only yield the part that hasn't been yielded yet
                    if len(new_content) > already_yielded_len:
                        to_yield = new_content[already_yielded_len:]
                        continue_text += to_yield
                        full_response += to_yield
                        yield to_yield
                else:
                    # Normal case: LLM is generating new content
                    continue_text += content
                    full_response += content
                    yield content

            if hasattr(choice, 'finish_reason') and choice.finish_reason:
                continue_finish_reason = choice.finish_reason

        if continue_text:
            llm_logger.info(f"✅ Continued generation (attempt {retry_count}): {repr(continue_text)} (finish_reason: {continue_finish_reason})")

            # Update finish_reason for next iteration check
            finish_reason = continue_finish_reason

            # If we got a complete last sentence or stopped for a reason other than length, break
            if is_last_sentence_complete(full_response) or continue_finish_reason != "length":
                break
        else:
            # No content generated, break to avoid infinite loop
            break

    # If still incomplete after all retries, apply truncate_to_complete_sentence as fallback
    if not sentence_end_re.search(full_response):
        original_length = len(full_response)
        full_response = truncate_to_complete_sentence(full_response)
        if len(full_response) < original_length:
            llm_logger.warning(f"⚠️ Applied truncate_to_complete_sentence: removed {original_length - len(full_response)} characters from end")

    # Log LLM output
    llm_logger.info("📤 LLM Response (MCP):")
    if len(full_response) > 500:
        llm_logger.info(f"{full_response[:500]}... [truncated]")
    else:
        llm_logger.info(full_response)
    llm_logger.info(f"Total length: {len(full_response)} characters")
    llm_logger.info(f"Finish reason: {finish_reason or continue_finish_reason}")
    llm_logger.info("=" * 80)


__all__ = [
    "DEFAULT_MODEL",
    "stream_llm",
    "CHAT_MODE_SYSTEM_PROMPT",
    "NARRATION_MODE_SYSTEM_PROMPT",
    "get_character_modified_system_prompt",
]
