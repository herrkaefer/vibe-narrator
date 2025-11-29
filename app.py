"""Vibe Narrator - Gradio UI with MCP Server Integration"""

import gradio as gr
import base64
import json
import asyncio
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file (if exists)
# This won't override existing environment variables (e.g., from Space settings)
load_dotenv()

# Import underlying functions and classes
from narrator_mcp.server import generate_narration, generate_narration_stream, AppContext
from narrator_mcp.characters import get_characters_list, get_character
from narrator_mcp.session import Session, DEFAULT_MODEL, DEFAULT_VOICE, DEFAULT_MODE
from narrator_mcp.chunker import Chunker
from narrator_mcp.tts import detect_tts_provider
from narrator_mcp.llm import CHAT_MODE_SYSTEM_PROMPT, get_character_modified_system_prompt

# Simple, neutral system prompt for chatbox (no character styling)
CHATBOX_SYSTEM_PROMPT = """You are a helpful AI assistant. Keep your responses brief and concise - aim for 1-3 sentences maximum. Be direct and to the point."""

# Get API keys from environment (provider-specific)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "nova")  # Default to "nova"
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_TTS_VOICE = os.getenv("ELEVENLABS_TTS_VOICE", "")  # Default empty, will be set from voice selection

# Get available characters
CHARACTERS = get_characters_list()
CHARACTER_CHOICES = {f"{char['name']}": char['id'] for char in CHARACTERS}
DEFAULT_CHARACTER = "The Reluctant Developer"

# Character descriptions for tooltips
CHARACTER_DESCRIPTIONS = {
    "The Burned-Out Developer": "Flat, drained, deeply unenthusiastic - debugging fatigue incarnate",
    "The Overconfident Senior Developer": "Energetic, smug, wrong about everything but says it with authority",
    "The Reluctant Developer": "Exhausted, unmotivated, begrudgingly compliant - every sentence sounds forced",
    "The Enlightened Zen Developer": "Calm, serene, meditative - code is a path to enlightenment",
    "The Adoring Fanboy": "Extremely enthusiastic, worshipful - every line of code is a masterpiece",
    "The Whispering ASMR Developer": "Soft, intimate, soothing - code explained with ASMR-like tranquility",
}

# Voice options (OpenAI TTS voices) - hardcoded list from OpenAI documentation
# Available voices: alloy, ash, ballad, coral, echo, fable, nova, onyx, sage, shimmer
VOICE_OPTIONS = ["alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer"]

# TTS Provider options
TTS_PROVIDER_OPTIONS = ["OpenAI TTS", "ElevenLabs TTS"]

# ElevenLabs premade voices (hardcoded from public API)
ELEVENLABS_PREMADE_VOICES = [
    {"name": "Roger", "voice_id": "CwhRBWXzGAHq8TQ4Fs17"},
    {"name": "Sarah", "voice_id": "EXAVITQu4vr4xnSDxMaL"},
    {"name": "Laura", "voice_id": "FGY2WhTYpPnrIDTdsKH5"},
    {"name": "Charlie", "voice_id": "IKne3meq5aSn9XLyUdCD"},
    {"name": "George", "voice_id": "JBFqnCBsd6RMkjVDRZzb"},
    {"name": "Callum", "voice_id": "N2lVS1w4EtoT3dr4eOWO"},
    {"name": "River", "voice_id": "SAz9YHcvj6GT2YYXdXww"},
    {"name": "Harry", "voice_id": "SOYHLrjzK2X1ezoPC6cr"},
    {"name": "Liam", "voice_id": "TX3LPaxmHKxFdv7VOQHJ"},
    {"name": "Alice", "voice_id": "Xb7hH8MSUJpSbSDYk0k2"},
    {"name": "Matilda", "voice_id": "XrExE9yKIg1WjnnlVkGX"},
    {"name": "Will", "voice_id": "bIHbv24MWmeRgasZH58o"},
    {"name": "Jessica", "voice_id": "cgSgspJ2msm6clMCkdW9"},
    {"name": "Eric", "voice_id": "cjVigY5qzO86Huf0OWal"},
    {"name": "Chris", "voice_id": "iP95p4xoKVk53GoZ742B"},
    {"name": "Brian", "voice_id": "nPczCjzI2devNBz1zQrb"},
    {"name": "Daniel", "voice_id": "onwK4e9ZLuTAKqWW03F9"},
    {"name": "Lily", "voice_id": "pFZP5JQG7iQjIQuC4Bku"},
    {"name": "Adam", "voice_id": "pNInz6obpgDQGcFmaJgB"},
    {"name": "Bill", "voice_id": "pqHfZKP75CvOlQylNhV4"},
]

# Cache for ElevenLabs voices (for custom voices from API)
_elevenlabs_voices: list[dict] = []
_elevenlabs_voice_choices: list[str] = []

# Model options - only GPT-4 and GPT-5 series
MODEL_OPTIONS = ["gpt-4o-mini", "gpt-4o", "gpt-5", "gpt-5.1"]

# Global session state for MCP tools
_global_session = Session()
_global_chunker = Chunker(max_tokens=12, sentence_boundary=True)
_global_context = AppContext(session=_global_session, chunker=_global_chunker)


def configure(
    llm_api_key: str,
    llm_model: str | None = None,
    voice: str | None = None,
    mode: str | None = None,
    character: str | None = None,
    base_url: str | None = None,
    default_headers: dict | None = None,
    tts_api_key: str | None = None,
    tts_provider: str | None = None,
) -> str:
    """Configure API credentials and narration settings for the session.

    This function sets up the default configuration that will be used by
    narrate_text when parameters are not explicitly provided.

    Args:
        llm_api_key: OpenAI API key for LLM (required)
        llm_model: LLM model to use (optional)
        voice: TTS voice selection (optional)
        mode: Mode selection - "narration" or "chat" (optional)
        character: Character ID (optional)
        base_url: Custom base URL for API (optional, e.g., for OpenRouter)
        default_headers: Custom headers for API requests (optional)
        tts_api_key: API key for TTS (optional, uses llm_api_key if not provided)
        tts_provider: TTS provider - "openai" or "elevenlabs" (optional, auto-detected)

    Returns:
        Success message string
    """
    global _global_session

    _global_session.llm_api_key = llm_api_key
    if llm_model is not None:
        _global_session.llm_model = llm_model
    if voice is not None:
        _global_session.voice = voice
    if mode is not None:
        _global_session.mode = mode
    if character is not None:
        _global_session.character = character
    if base_url is not None:
        _global_session.base_url = base_url
    if default_headers is not None:
        _global_session.default_headers = default_headers
    if tts_api_key is not None:
        _global_session.tts_api_key = tts_api_key
    else:
        # If tts_api_key is None, set it to llm_api_key
        _global_session.tts_api_key = llm_api_key

    # Set TTS provider (auto-detect if not provided)
    if tts_provider is not None:
        _global_session.tts_provider = tts_provider
    elif _global_session.tts_api_key:
        # Auto-detect provider from API key format
        _global_session.tts_provider = detect_tts_provider(_global_session.tts_api_key)
    else:
        _global_session.tts_provider = None

    return "Configuration updated successfully"


def get_config_status() -> str:
    """Get the current configuration status for debugging.

    Returns:
        JSON string with current configuration status
    """
    global _global_session
    session = _global_session

    # Build status dictionary
    status = {
        "has_api_key": session.llm_api_key is not None,
        "has_tts_api_key": session.tts_api_key is not None,
        "is_configured": session.llm_api_key is not None and session.tts_api_key is not None,
        "session": {
            "model": session.llm_model,
            "voice": session.voice,
            "mode": session.mode,
            "character": session.character or "default",
            "base_url": session.base_url,
            "has_default_headers": session.default_headers is not None,
            "tts_provider": session.tts_provider or "auto-detect",
        }
    }

    # Add default_headers keys if present (without values for security)
    if session.default_headers:
        status["session"]["default_headers_keys"] = list(session.default_headers.keys())

    return json.dumps(status)


async def narrate_text(
    prompt: str,
    character: str | None = None,
    voice: str | None = None,
    model: str | None = None,
    tts_provider: str | None = None,
    llm_api_key: str | None = None,
    tts_api_key: str | None = None,
    openai_tts_api_key: str | None = None,
    openai_tts_voice: str | None = None,
    elevenlabs_tts_api_key: str | None = None,
    elevenlabs_tts_voice: str | None = None,
) -> str:
    """Generate narrated speech with personality using LLM and TTS.

    This function takes text input and converts it to narrated speech with
    a selected character personality. The LLM interprets the text in the
    character's voice, and TTS generates the audio.

    If parameters are not provided, they will be taken from the session
    configuration (set via configure tool). For UI usage, all parameters
    should be provided.

    Args:
        prompt: The text to narrate (required)
        character: Character personality name (optional, uses session default if not provided)
        voice: TTS voice selection (optional, uses session default if not provided)
        model: LLM model to use (optional, uses session default if not provided)
        tts_provider: TTS provider ("OpenAI TTS" or "ElevenLabs TTS", optional)
        llm_api_key: OpenAI API key for LLM (optional, uses session or env var)
        tts_api_key: API key for TTS (optional, uses session or llm_api_key)

    Returns:
        Tuple of (audio_file_path, generated_text) or (None, error_message)
    """
    if not prompt or not prompt.strip():
        error_result = {
            "text": "",
            "audio": "",
            "format": "mp3",
            "error": "Please enter some text to narrate."
        }
        return json.dumps(error_result)

    global _global_session, _global_context

    # Determine API keys (prefer parameters, then session, then environment variables)
    final_llm_api_key = llm_api_key or _global_session.llm_api_key or OPENAI_API_KEY
    if not final_llm_api_key:
        error_result = {
            "text": "",
            "audio": "",
            "format": "mp3",
            "error": "Error: OPENAI_API_KEY not provided. Please configure using configure tool or set environment variable."
        }
        return json.dumps(error_result)

    # Use session defaults if parameters not provided
    final_model = model or _global_session.llm_model
    final_voice = voice or _global_session.voice
    final_mode = "narration"  # Fixed to narration mode for UI
    final_character_id = None

    # Note: Voice ID extraction is now handled in provider-specific sections above

    # Handle character: can be character name (from UI) or character ID (from MCP)
    if character:
        # Check if it's a character name (from UI dropdown) or character ID (from MCP)
        if character in CHARACTER_CHOICES:
            final_character_id = CHARACTER_CHOICES[character]
        else:
            # Assume it's already a character ID
            final_character_id = character
    else:
        # Use session default
        final_character_id = _global_session.character or "reluctant_developer"

    # Determine TTS provider and API key (use provider-specific parameters if provided)
    final_tts_api_key = tts_api_key
    tts_provider_value = None

    if tts_provider:
        # Parse tts_provider string (from UI) or use directly (from MCP)
        if tts_provider == "ElevenLabs TTS":
            tts_provider_value = "elevenlabs"
        elif tts_provider == "OpenAI TTS":
            tts_provider_value = "openai"
        else:
            # Assume it's already a provider value
            tts_provider_value = tts_provider
    else:
        # Use session default
        tts_provider_value = _global_session.tts_provider

    # Use provider-specific API keys and voices if provided (from UI)
    if tts_provider_value == "elevenlabs":
        # Use ElevenLabs-specific parameters
        # API key comes from environment variable only
        final_tts_api_key = ELEVENLABS_API_KEY or _global_session.tts_api_key

        if elevenlabs_tts_voice and elevenlabs_tts_voice.strip():
            # Convert voice name to voice_id
            voice_name = elevenlabs_tts_voice.strip()
            voice_id = get_elevenlabs_voice_id_by_name(voice_name)
            if voice_id:
                final_voice = voice_id
            else:
                # If not found in premade voices, assume it's already a voice_id
                final_voice = voice_name
        elif not final_voice:
            # Try to get voice_id from environment variable (if it's a name, convert it)
            env_voice = ELEVENLABS_TTS_VOICE or _global_session.voice
            if env_voice:
                voice_id = get_elevenlabs_voice_id_by_name(env_voice)
                final_voice = voice_id if voice_id else env_voice
            else:
                final_voice = None

        if not final_tts_api_key:
            error_result = {
                "text": "",
                "audio": "",
                "format": "mp3",
                "error": "Error: ELEVENLABS_API_KEY not provided. Please set it in environment variables."
            }
            return json.dumps(error_result)
    else:
        # Use OpenAI-specific parameters (default)
        if openai_tts_api_key and openai_tts_api_key.strip():
            final_tts_api_key = openai_tts_api_key.strip()
        elif not final_tts_api_key:
            # Use LLM API key for TTS if TTS key not provided
            final_tts_api_key = _global_session.tts_api_key or final_llm_api_key

        if openai_tts_voice and openai_tts_voice.strip():
            final_voice = openai_tts_voice.strip()
        elif not final_voice:
            final_voice = OPENAI_TTS_VOICE or _global_session.voice

    # Auto-detect TTS provider if not explicitly set
    if not tts_provider_value and final_tts_api_key:
        tts_provider_value = detect_tts_provider(final_tts_api_key) or "openai"

    try:
        # Create temporary session for this request (use provided values or session defaults)
        session = Session()
        session.llm_api_key = final_llm_api_key
        session.llm_model = final_model
        session.voice = final_voice
        session.mode = final_mode
        session.character = final_character_id
        session.tts_api_key = final_tts_api_key
        session.tts_provider = tts_provider_value
        session.base_url = _global_session.base_url
        session.default_headers = _global_session.default_headers

        chunker = Chunker(max_tokens=12, sentence_boundary=True)
        ctx = AppContext(session=session, chunker=chunker)

        # Generate narration directly
        text, audio_bytes = await generate_narration(ctx, prompt)

        # Return as JSON with base64-encoded audio (consistent with local MCP server)
        # This format works for both MCP API calls and can be parsed by UI wrapper
        result = {
            "text": text,
            "audio": base64.b64encode(audio_bytes).decode('utf-8'),
            "format": "mp3"
        }
        return json.dumps(result)

    except Exception as e:
        error_msg = f"❌ Error generating narration: {str(e)}"
        # Return error as JSON format (consistent with success case)
        error_result = {
            "text": "",
            "audio": "",
            "format": "mp3",
            "error": error_msg
        }
        return json.dumps(error_result)


def get_character_info():
    """Get information about available characters"""
    info = "Available Characters:\n\n"
    for char in CHARACTERS:
        info += f"- {char['name']} ({char['id']})\n"
    return info


def list_characters() -> str:
    """List all available character personalities.

    Returns a JSON string with information about all available character
    personalities that can be used for narration.

    Returns:
        JSON string with characters array, each containing id, name, and description
    """
    return json.dumps({"characters": CHARACTERS})


def get_elevenlabs_voice_id_by_name(name: str) -> str | None:
    """Get ElevenLabs voice_id by name.

    Args:
        name: Voice name

    Returns:
        Voice ID if found, None otherwise
    """
    for voice in ELEVENLABS_PREMADE_VOICES:
        if voice['name'] == name:
            return voice['voice_id']
    return None


def get_elevenlabs_voices() -> tuple[list[str], str]:
    """Get available ElevenLabs voices.

    Returns premade voices (hardcoded) immediately, no API call needed.
    Returns only voice names (not IDs) for UI display.

    Returns:
        Tuple of (voice_names_list, status_message)
    """
    global _elevenlabs_voice_choices

    # Use hardcoded premade voices - return only names
    voice_names = [voice['name'] for voice in ELEVENLABS_PREMADE_VOICES]
    _elevenlabs_voice_choices = voice_names
    return voice_names, f"✅ Loaded {len(voice_names)} ElevenLabs premade voices"


async def fetch_elevenlabs_voices() -> tuple[list[str], str]:
    """Async wrapper for get_elevenlabs_voices (for compatibility)."""
    return get_elevenlabs_voices()


def _convert_history_to_dict_format(history):
    """Convert history from old format [[user, assistant], ...] to new format [{"role": "user", "content": "..."}, ...]."""
    new_history = []
    for item in history:
        if isinstance(item, dict) and "role" in item and "content" in item:
            # Already in new format
            new_history.append(item)
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            # Old format: [user_msg, assistant_msg]
            user_msg = item[0] if item[0] else ""
            assistant_msg = item[1] if item[1] else ""
            if user_msg:
                new_history.append({"role": "user", "content": user_msg})
            if assistant_msg:
                new_history.append({"role": "assistant", "content": assistant_msg})
    return new_history


def _convert_history_to_old_format(history):
    """Convert history from new format to old format for LLM function."""
    old_history = []
    user_msg = None
    for item in history:
        if isinstance(item, dict) and "role" in item:
            role = item.get("role")
            content = item.get("content", "")
            if role == "user":
                user_msg = content
            elif role == "assistant" and user_msg is not None:
                old_history.append([user_msg, content])
                user_msg = None
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            # Already in old format
            old_history.append([item[0], item[1]])
    return old_history


async def generate_chat_response(
    message: str,
    history: list,
    character: str,
    model: str,
    llm_api_key: str,
    base_url: str | None = None,
    default_headers: dict | None = None,
) -> str:
    """Generate chat response using LLM with conversation history.

    Args:
        message: Current user message
        history: Conversation history (list of dicts with 'role' and 'content' keys)
        character: Character name or ID
        model: LLM model to use
        llm_api_key: OpenAI API key
        base_url: Custom base URL for API
        default_headers: Custom headers for API requests

    Returns:
        Generated response text
    """
    import openai

    # Get character object
    if character in CHARACTER_CHOICES:
        character_id = CHARACTER_CHOICES[character]
    else:
        character_id = character

    char_obj = get_character(character_id)

    # Build messages from history
    messages = []

    # Add system prompt with character
    system_prompt = get_character_modified_system_prompt(
        base_system_prompt=CHAT_MODE_SYSTEM_PROMPT,
        character=char_obj,
    )
    messages.append({"role": "system", "content": system_prompt})

    # Convert Gradio history format to OpenAI format
    # Gradio history: list of [user_msg, assistant_msg] pairs
    # OpenAI format: list of {"role": "user"/"assistant", "content": "..."}
    for pair in history:
        if len(pair) >= 2:
            user_msg = pair[0]
            assistant_msg = pair[1]
            if user_msg:
                messages.append({"role": "user", "content": user_msg})
            if assistant_msg:
                messages.append({"role": "assistant", "content": assistant_msg})

    # Add current message
    messages.append({"role": "user", "content": message})

    # Call OpenAI API
    client_kwargs = {"api_key": llm_api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    if default_headers:
        client_kwargs["default_headers"] = default_headers

    client = openai.AsyncOpenAI(**client_kwargs)

    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,  # Use streaming for progressive display
    )

    # Accumulate streamed response
    full_response = ""
    async for chunk in response:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        content = delta.content if hasattr(delta, 'content') else None
        if content:
            full_response += content

    return full_response


# Create the Gradio interface
with gr.Blocks(title="Vibe Narrator - Stylized Voice Embodiment") as demo:
    gr.Markdown("# 🎨 Vibe Narrator")
    gr.Markdown("Stylized voice embodiment for terminal agents. Give your code a voice with personality!")

    # Display logo if available
    logo_path = Path(__file__).parent / "logo.png"
    if logo_path.exists():
        gr.Image(str(logo_path), show_label=False, container=False, height=120)

    with gr.Tabs():
        # Main Narration Tab - Redesigned with video placeholder and workflow explanation
        with gr.Tab("Narrate"):
            with gr.Row():
                with gr.Column(scale=2):
                    gr.Markdown("## 🎬 Demo Videos")

                    # Video placeholder
                    gr.Markdown("""
                    <div style="text-align: center; padding: 40px; background-color: #f0f0f0; border-radius: 8px; margin: 20px 0;">
                        <h3>📹 Demo Videos Coming Soon</h3>
                        <p>I am preparing screen demonstration videos to showcase Vibe Narrator's workflow.</p>
                        <p><em>Demo videos coming soon...</em></p>
                    </div>
                    """)

                    # Placeholder for future YouTube video embedding
                    # Uncomment and update when videos are ready:
                    # gr.HTML("""
                    # <div style="text-align: center; margin: 20px 0;">
                    #     <iframe width="560" height="315"
                    #             src="https://www.youtube.com/embed/YOUR_VIDEO_ID"
                    #             frameborder="0"
                    #             allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                    #             allowfullscreen>
                    #     </iframe>
                    # </div>
                    # """)

                    gr.Markdown("## 📖 How It Works")

                    with gr.Accordion("🔄 Workflow", open=True):
                        gr.Markdown("""
                        ### Terminal Agent Integration

                        Vibe Narrator uses a **bridge tool** (`terminal_client/bridge.py`) to capture terminal output from your coding agents and convert it into stylized voice narration.

                        **Process:**
                        1. The bridge tool runs your terminal agent (e.g., `claude`, `cursor`, etc.) in a PTY (pseudo-terminal)
                        2. Terminal output is captured and buffered
                        3. Text chunks are sent to the MCP server via the `narrate_text` tool
                        4. The LLM interprets the text in your chosen character's personality
                        5. TTS generates audio with the character's voice
                        6. Audio is played in real-time through your speakers

                        This creates a seamless, hands-free narration experience during your coding sessions.
                        """)

                    with gr.Accordion("🔌 Bridge Tool", open=False):
                        gr.Markdown("""
                        ### What is the Bridge Tool?

                        The bridge tool (`terminal_client/bridge.py`) is a Python script that:

                        - **Captures terminal output**: Uses PTY to capture stdout/stderr from any command
                        - **Cleans ANSI codes**: Removes terminal formatting codes for clean text
                        - **Buffers intelligently**: Accumulates output before sending for narration
                        - **Connects to MCP**: Uses the official MCP client SDK to communicate with the narrator server
                        - **Plays audio**: Handles real-time audio playback as narration is generated

                        **Usage Example:**
                        ```bash
                        uv run python bridge.py claude
                        ```

                        This runs the `claude` command with narration enabled. All agent output will be automatically narrated with your chosen character's voice.
                        """)

                    with gr.Accordion("🌐 Compatibility", open=False):
                        gr.Markdown("""
                        ### Terminal Agent Compatibility

                        Vibe Narrator is compatible with any terminal-based agent through the MCP (Model Context Protocol) standard:

                        - **Cursor**: Configure MCP server in Cursor settings
                        - **Claude Desktop**: Add narrator-mcp to MCP servers configuration
                        - **Custom Agents**: Any tool that supports MCP protocol
                        - **Command-line Tools**: Use the bridge tool with any command

                        The MCP protocol ensures universal compatibility - as long as your agent can communicate via MCP, Vibe Narrator can narrate its output.

                        **Why MCP?**
                        - Standard protocol for AI tool integration
                        - Works across different platforms and agents
                        - No vendor lock-in
                        - Easy to configure and use
                        """)

                with gr.Column(scale=1):
                    gr.Markdown("## 📝 Try It Out")

                    prompt_input = gr.Textbox(
                        label="Text to Narrate",
                        placeholder="Enter the text you want to narrate...",
                        lines=8,
                        value="",
                    )

                    gr.Markdown("## ⚙️ Configuration")

                    gr.Markdown("**Character**")
                    character_radio = gr.Radio(
                        label="Character",
                        choices=list(CHARACTER_CHOICES.keys()),
                        value=DEFAULT_CHARACTER,
                    )
                    character_state = gr.State(value=DEFAULT_CHARACTER)

                    # Update character_state when radio selection changes
                    def update_character_state(selected_character):
                        return selected_character

                    character_radio.change(
                        fn=update_character_state,
                        inputs=[character_radio],
                        outputs=[character_state],
                    )

                    model_dropdown = gr.Dropdown(
                        label="LLM Model",
                        choices=MODEL_OPTIONS,
                        value=DEFAULT_MODEL,
                        info="GPT model for text generation",
                        allow_custom_value=False,
                    )

                    tts_provider_input = gr.Dropdown(
                        label="TTS Provider",
                        choices=TTS_PROVIDER_OPTIONS,
                        value="OpenAI TTS",
                        info="Choose TTS service provider",
                        allow_custom_value=False,
                    )

                    # Voice dropdown - will be updated based on provider
                    voice_dropdown_unified = gr.Dropdown(
                        label="Voice",
                        choices=VOICE_OPTIONS,
                        value=OPENAI_TTS_VOICE,
                        info="TTS voice selection",
                        allow_custom_value=False,
                    )

                    # Hidden groups for status tracking (not visible in UI)
                    openai_tts_group = gr.Group(visible=False)
                    elevenlabs_tts_group = gr.Group(visible=False)
                    elevenlabs_voice_status = gr.Textbox(
                        label="Voice Status",
                        value="",
                        interactive=False,
                        visible=False,
                    )

                    # Legacy voice dropdown (hidden, kept for compatibility)
                    voice_dropdown = gr.Dropdown(
                        label="Voice",
                        choices=VOICE_OPTIONS,
                        value=DEFAULT_VOICE,
                        info="TTS voice selection",
                        visible=False,
                        allow_custom_value=False,
                    )

                    voice_status = gr.Textbox(
                        label="Voice Status",
                        value="",
                        interactive=False,
                        visible=False,
                    )

                    narrate_btn = gr.Button("🎤 Generate Narration", variant="primary", size="lg")

                with gr.Column(scale=1):
                    gr.Markdown("## 🎵 Output")

                    audio_output = gr.Audio(
                        label="Generated Audio",
                        type="filepath",
                        interactive=False,
                    )

                    # HTML component for streaming audio playback
                    streaming_audio_html = gr.HTML(
                        label="Streaming Audio",
                        visible=True,
                    )

                    text_output = gr.Textbox(
                        label="Generated Text",
                        lines=12,
                        interactive=False,
                    )

        # Chat Tab
        with gr.Tab("Chat"):
            with gr.Row():
                with gr.Column(scale=3):
                    # Chat configuration state
                    chat_character_state = gr.State(value=DEFAULT_CHARACTER)
                    chat_model_state = gr.State(value=DEFAULT_MODEL)
                    chat_tts_provider_state = gr.State(value="OpenAI TTS")
                    chat_voice_state = gr.State(value=OPENAI_TTS_VOICE)

                    # Chatbot component
                    chatbot = gr.Chatbot(
                        label="💬 Chat with Vibe Narrator",
                        height=500,
                    )

                    # Hidden audio component for auto-play
                    chat_audio_output = gr.Audio(
                        type="filepath",
                        visible=False,
                    )

                    # HTML component for audio auto-play
                    chat_audio_html = gr.HTML(
                        visible=True,  # Make visible for debugging
                    )

                    # Chat input - enable Enter to submit
                    msg = gr.Textbox(
                        label="Message",
                        placeholder="Type your message here and press Enter to send...",
                        lines=2,
                    )

                    # Chat function with streaming
                    async def chat_function(message, history):
                        """Chat function that generates response and audio with streaming."""
                        if not message or not message.strip():
                            yield history, "", None, ""
                            return

                        # Get configuration from state
                        character = chat_character_state.value
                        model = chat_model_state.value
                        tts_provider = chat_tts_provider_state.value
                        voice = chat_voice_state.value

                        # Get API key
                        llm_api_key = OPENAI_API_KEY
                        if not llm_api_key:
                            error_msg = "❌ Error: OPENAI_API_KEY not configured. Please set it in environment variables."
                            # Use dict format for Gradio Chatbot
                            new_history = _convert_history_to_dict_format(history)
                            new_history.append({"role": "user", "content": message})
                            new_history.append({"role": "assistant", "content": error_msg})
                            yield new_history, "", None, ""
                            return

                        # Immediately add user message to history and yield
                        # Use dict format for Gradio Chatbot
                        new_history = _convert_history_to_dict_format(history)
                        new_history.append({"role": "user", "content": message})
                        new_history.append({"role": "assistant", "content": ""})  # Empty assistant message for streaming
                        yield new_history, "", None, ""

                        try:
                            # Convert history format for LLM (expects old format)
                            old_format_history = _convert_history_to_old_format(history)

                            # Build messages from history
                            # Use simple, neutral prompt for chatbox (no character styling)
                            messages = []
                            messages.append({"role": "system", "content": CHATBOX_SYSTEM_PROMPT})

                            # Add history
                            for pair in old_format_history:
                                if len(pair) >= 2:
                                    user_msg = pair[0]
                                    assistant_msg = pair[1]
                                    if user_msg:
                                        messages.append({"role": "user", "content": user_msg})
                                    if assistant_msg:
                                        messages.append({"role": "assistant", "content": assistant_msg})

                            # Add current message
                            messages.append({"role": "user", "content": message})

                            # Stream LLM response
                            import openai
                            client_kwargs = {"api_key": llm_api_key}
                            if _global_session.base_url:
                                client_kwargs["base_url"] = _global_session.base_url
                            if _global_session.default_headers:
                                client_kwargs["default_headers"] = _global_session.default_headers

                            client = openai.AsyncOpenAI(**client_kwargs)

                            ai_response = ""
                            # Await the coroutine to get the async iterator
                            stream = await client.chat.completions.create(
                                model=model,
                                messages=messages,
                                stream=True,
                            )
                            async for chunk in stream:
                                if not chunk.choices:
                                    continue
                                delta = chunk.choices[0].delta
                                content = delta.content if hasattr(delta, 'content') else None
                                if content:
                                    ai_response += content
                                    # Update history with streaming response
                                    # Use dict format for Gradio Chatbot
                                    streaming_history = _convert_history_to_dict_format(history)
                                    streaming_history.append({"role": "user", "content": message})
                                    streaming_history.append({"role": "assistant", "content": ai_response})
                                    yield streaming_history, "", None, ""

                            if not ai_response:
                                # Use dict format for Gradio Chatbot
                                final_history = _convert_history_to_dict_format(history)
                                final_history.append({"role": "user", "content": message})
                                final_history.append({"role": "assistant", "content": ""})
                                yield final_history, "", None, ""
                                return

                            # Generate audio from AI response using MCP narrate_text
                            # This will apply character styling to the response
                            session = Session()
                            session.llm_api_key = llm_api_key
                            session.llm_model = model
                            session.voice = voice
                            session.mode = "chat"  # Use chat mode
                            if character in CHARACTER_CHOICES:
                                session.character = CHARACTER_CHOICES[character]
                            else:
                                session.character = character

                            # Determine TTS provider and API key
                            if tts_provider == "ElevenLabs TTS":
                                tts_provider_value = "elevenlabs"
                                tts_api_key = ELEVENLABS_API_KEY or llm_api_key
                            else:
                                tts_provider_value = "openai"
                                tts_api_key = llm_api_key

                            session.tts_api_key = tts_api_key
                            session.tts_provider = tts_provider_value
                            session.base_url = _global_session.base_url
                            session.default_headers = _global_session.default_headers

                            chunker = Chunker(max_tokens=12, sentence_boundary=True)
                            ctx = AppContext(session=session, chunker=chunker)

                            # Generate narration (audio) from AI response
                            # In chat mode, generate_narration will re-process the text with character styling for audio
                            styled_text, audio_bytes = await generate_narration(ctx, ai_response)

                            # History already contains the final response from streaming, update with combined content
                            # Use dict format for Gradio Chatbot
                            final_history = _convert_history_to_dict_format(history)
                            final_history.append({"role": "user", "content": message})

                            # Create content with two separate visual boxes: AI response and MCP styled text
                            if styled_text and styled_text.strip() and styled_text != ai_response:
                                # Escape HTML special characters in styled_text, but preserve line breaks
                                import html
                                escaped_styled = html.escape(styled_text).replace('\n', '<br>')

                                # Create two separate visual boxes in HTML
                                # First box: AI original response
                                # Second box: MCP styled text
                                combined_content = f"""<div style="margin-bottom: 16px;">
<div style="padding: 12px 16px; background: #ffffff; border: 1px solid #e0e0e0; border-radius: 8px; margin-bottom: 12px;">
{html.escape(ai_response).replace(chr(10), '<br>')}
</div>
<div style="padding: 12px 16px; background: linear-gradient(to right, #f8f9fa, #e9ecef); border-left: 4px solid #6c757d; border-radius: 6px; font-style: italic; color: #495057; font-size: 0.95em; line-height: 1.6;">
<strong style="color: #495057; display: block; margin-bottom: 8px;">🎭</strong>
<span style="color: #6c757d; display: block;">{escaped_styled}</span>
</div>
</div>"""
                            else:
                                # Only AI response, no styled text
                                import html
                                combined_content = html.escape(ai_response).replace(chr(10), '<br>')

                            final_history.append({"role": "assistant", "content": combined_content})

                            # Save audio to temporary file for playback
                            import tempfile
                            import time
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                                f.write(audio_bytes)
                                audio_path = f.name

                            # Create HTML with auto-play audio using base64 data URL
                            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
                            audio_data_url = f"data:audio/mpeg;base64,{audio_base64}"
                            audio_id = f"chat-audio-{int(time.time() * 1000000)}"

                            audio_html = f"""
                            <div id="audio-container-{audio_id}" style="border: 1px solid #ccc; padding: 10px; margin: 10px 0; background: #f9f9f9;">
                                <p><strong>Audio Debug Info:</strong></p>
                                <p>Audio ID: {audio_id}</p>
                                <p>Audio size: {len(audio_bytes)} bytes</p>
                                <p id="audio-status-{audio_id}">Status: Loading...</p>
                                <audio id="{audio_id}" controls autoplay preload="auto" style="width: 100%; margin-top: 10px;">
                                    <source src="{audio_data_url}" type="audio/mpeg">
                                </audio>
                            </div>
                            <script>
                            (function() {{
                                const audioId = '{audio_id}';
                                console.log('🎵 Initializing audio:', audioId);

                                function initAndPlay() {{
                                    const audio = document.getElementById(audioId);
                                    const statusEl = document.getElementById('audio-status-' + audioId);

                                    if (!audio) {{
                                        console.log('⏳ Audio element not found yet, retrying...');
                                        setTimeout(initAndPlay, 100);
                                        return;
                                    }}

                                    console.log('✅ Audio element found:', audioId);
                                    if (statusEl) statusEl.textContent = 'Status: Found, initializing...';

                                    // Stop all other playing audios
                                    const allAudios = document.querySelectorAll('audio');
                                    allAudios.forEach(a => {{
                                        if (a !== audio && !a.paused) {{
                                            console.log('⏹️ Stopping other audio:', a.id);
                                            a.pause();
                                            a.currentTime = 0;
                                        }}
                                    }});

                                    // Event listeners
                                    audio.addEventListener('canplay', () => {{
                                        console.log('▶️ Audio can play:', audioId);
                                        if (statusEl) statusEl.textContent = 'Status: Ready to play';
                                        tryPlay();
                                    }});

                                    audio.addEventListener('play', () => {{
                                        console.log('🎵 Audio playing:', audioId);
                                        if (statusEl) statusEl.textContent = 'Status: Playing';
                                    }});

                                    audio.addEventListener('error', (e) => {{
                                        console.error('❌ Audio error:', audioId, e, audio.error);
                                        if (statusEl) statusEl.textContent = 'Status: ERROR - ' + (audio.error ? audio.error.message : 'Unknown');
                                    }});

                                    // Load and try to play
                                    audio.load();
                                    console.log('🔄 Audio loaded:', audioId);

                                    // Try playing multiple times with delays
                                    function tryPlay() {{
                                        if (audio.paused) {{
                                            const playPromise = audio.play();
                                            if (playPromise !== undefined) {{
                                                playPromise.then(() => {{
                                                    console.log('✅ Audio playing successfully:', audioId);
                                                    if (statusEl) statusEl.textContent = 'Status: Playing';
                                                }}).catch(e => {{
                                                    console.error('❌ Play prevented:', audioId, e);
                                                    if (statusEl) statusEl.textContent = 'Status: Waiting for interaction';
                                                    // Retry on interaction
                                                    const retry = () => {{
                                                        audio.play().catch(() => {{}});
                                                        document.removeEventListener('click', retry);
                                                        document.removeEventListener('keydown', retry);
                                                    }};
                                                    document.addEventListener('click', retry, {{ once: true }});
                                                    document.addEventListener('keydown', retry, {{ once: true }});
                                                }});
                                            }}
                                        }}
                                    }}

                                    // Try immediately and with delays
                                    setTimeout(tryPlay, 100);
                                    setTimeout(tryPlay, 300);
                                    setTimeout(tryPlay, 500);
                                }}

                                // Start initialization
                                if (document.readyState === 'loading') {{
                                    document.addEventListener('DOMContentLoaded', initAndPlay);
                                }} else {{
                                    setTimeout(initAndPlay, 50);
                                }}
                            }})();
                            </script>
                            """

                            # Final yield with audio
                            yield final_history, "", audio_path, audio_html

                        except Exception as e:
                            import traceback
                            error_msg = f"❌ Error: {str(e)}"
                            error_trace = traceback.format_exc()
                            logger.error(f"Chat function error: {error_msg}\n{error_trace}")
                            # Use dict format for Gradio Chatbot
                            error_history = _convert_history_to_dict_format(history)
                            error_history.append({"role": "user", "content": message})
                            error_history.append({"role": "assistant", "content": error_msg})
                            yield error_history, "", None, ""

                    # Submit button
                    submit_btn = gr.Button("Send", variant="primary")
                    clear_btn = gr.Button("Clear")

                    # Event handlers
                    msg.submit(
                        fn=chat_function,
                        inputs=[msg, chatbot],
                        outputs=[chatbot, msg, chat_audio_output, chat_audio_html],
                    )

                    submit_btn.click(
                        fn=chat_function,
                        inputs=[msg, chatbot],
                        outputs=[chatbot, msg, chat_audio_output, chat_audio_html],
                    )

                    clear_btn.click(
                        fn=lambda: ([], ""),
                        outputs=[chatbot, msg],
                    )

                with gr.Column(scale=1):
                    gr.Markdown("## ⚙️ Configuration")

                    chat_character_radio = gr.Radio(
                        label="Character",
                        choices=list(CHARACTER_CHOICES.keys()),
                        value=DEFAULT_CHARACTER,
                    )

                    def update_chat_character(selected_character):
                        chat_character_state.value = selected_character
                        return selected_character

                    chat_character_radio.change(
                        fn=update_chat_character,
                        inputs=[chat_character_radio],
                        outputs=[],
                    )

                    chat_model_dropdown = gr.Dropdown(
                        label="LLM Model",
                        choices=MODEL_OPTIONS,
                        value=DEFAULT_MODEL,
                        info="GPT model for chat",
                        allow_custom_value=False,
                    )

                    def update_chat_model(selected_model):
                        chat_model_state.value = selected_model
                        return selected_model

                    chat_model_dropdown.change(
                        fn=update_chat_model,
                        inputs=[chat_model_dropdown],
                        outputs=[],
                    )

                    chat_tts_provider_dropdown = gr.Dropdown(
                        label="TTS Provider",
                        choices=TTS_PROVIDER_OPTIONS,
                        value="OpenAI TTS",
                        info="Choose TTS service provider",
                        allow_custom_value=False,
                    )

                    def update_chat_tts_provider(selected_provider):
                        chat_tts_provider_state.value = selected_provider
                        return selected_provider

                    chat_tts_provider_dropdown.change(
                        fn=update_chat_tts_provider,
                        inputs=[chat_tts_provider_dropdown],
                        outputs=[],
                    )

                    chat_voice_dropdown = gr.Dropdown(
                        label="Voice",
                        choices=VOICE_OPTIONS,
                        value=OPENAI_TTS_VOICE,
                        info="TTS voice selection",
                        allow_custom_value=False,
                    )

                    def update_chat_voice(selected_voice):
                        chat_voice_state.value = selected_voice
                        return selected_voice

                    chat_voice_dropdown.change(
                        fn=update_chat_voice,
                        inputs=[chat_voice_dropdown],
                        outputs=[],
                    )

                    # Update voice dropdown when TTS provider changes
                    async def update_chat_voice_options(tts_provider: str):
                        if tts_provider == "ElevenLabs TTS":
                            return gr.Dropdown(
                                choices=[],
                                value=None,
                                visible=False,
                                info="Voice is automatically selected based on character",
                            )
                        else:
                            return gr.Dropdown(
                                choices=VOICE_OPTIONS,
                                value=OPENAI_TTS_VOICE,
                                visible=True,
                                info="OpenAI TTS voice selection",
                            )

                    chat_tts_provider_dropdown.change(
                        fn=update_chat_voice_options,
                        inputs=[chat_tts_provider_dropdown],
                        outputs=[chat_voice_dropdown],
                    )

        # MCP Info Tab
        with gr.Tab("MCP Server"):
            gr.Markdown("## MCP Server Information")
            gr.Markdown("""
            This Gradio app also exposes an MCP (Model Context Protocol) server that can be used by external clients.

            ### MCP Endpoint

            When deployed on Hugging Face Spaces, the MCP server is available at:
            ```
            https://mcp-1st-birthday-vibe-narrator.hf.space/gradio_api/mcp/sse
            ```

            ### Client Configuration

            Add this to your MCP client configuration (e.g., Claude Desktop):

            ```json
            {
              "mcpServers": {
                "narrator-mcp": {
                  "url": "https://mcp-1st-birthday-vibe-narrator.hf.space/gradio_api/mcp/sse"
                }
              }
            }
            ```

            ### Available MCP Tools

            - `configure`: Set up API keys and narration settings for the session
            - `narrate_text`: Generate narrated speech with personality (uses session config if parameters not provided)
            - `list_characters`: Get available character personalities
            - `get_config_status`: Check current configuration status

            ### Example Usage

            Once connected, you can ask Claude:
            - "Configure the narrator with my API key sk-... and use the zen_developer character"
            - "Narrate this text: [your text]"
            - "List available characters"
            - "Get the current configuration status"

            Note: For first-time use, call `configure` to set up API keys and default settings.
            After that, `narrate_text` can be called with just the prompt, using the configured defaults.
            """)

        # About Tab
        with gr.Tab("About"):
            gr.Markdown("""
            ## About Vibe Narrator

            Vibe Narrator is a tool that gives your terminal agents personality through stylized voice narration.

            ### Features

            - Multiple character personalities with distinct voices
            - Two modes: Narration (retelling) and Chat (conversation)
            - Support for OpenAI and ElevenLabs TTS
            - MCP server integration for external clients
            - Free deployment on Hugging Face Spaces

            ### How It Works

            1. Enter text to narrate
            2. Select a character personality
            3. Choose narration or chat mode
            4. Generate - LLM interprets the text in character, TTS creates audio

            ### GitHub

            https://github.com/herrkaefer/vibe-narrator

            ### License

            MIT License
            """)

    # Wrapper function for UI that only uses UI inputs
    async def narrate_text_ui(
        prompt: str,
        character: str,
        voice: str,  # Legacy, not used but kept for compatibility
        model: str,
        tts_provider: str,
        unified_voice: str,
    ) -> tuple[str | None, str]:
        """UI wrapper for narrate_text that handles provider-specific inputs."""
        # Convert empty strings to None
        voice_val = unified_voice.strip() if unified_voice and unified_voice.strip() else None

        # Determine which provider-specific voice parameter to use
        openai_voice_val = None
        elevenlabs_voice_val = None

        if tts_provider == "ElevenLabs TTS":
            elevenlabs_voice_val = voice_val
        else:
            openai_voice_val = voice_val

        # narrate_text now returns JSON string, parse it for UI
        result_json = await narrate_text(
            prompt=prompt,
            character=character,
            voice=None,  # Not used, provider-specific voices are used instead
            model=model,
            tts_provider=tts_provider,
            llm_api_key=None,  # Will use environment variable
            tts_api_key=None,  # Not used, provider-specific keys are used instead
            openai_tts_api_key=None,  # Will use OPENAI_API_KEY from environment
            openai_tts_voice=openai_voice_val,
            elevenlabs_tts_api_key=None,  # Will use ELEVENLABS_API_KEY from environment
            elevenlabs_tts_voice=elevenlabs_voice_val,
        )

        # Parse JSON result
        result = json.loads(result_json)

        # Check for error in result
        if "error" in result:
            error_msg = result.get("error", "Unknown error")
            return None, f"❌ {error_msg}"

        generated_text = result.get("text", "")
        audio_base64 = result.get("audio", "")

        # Save audio to temporary file for Gradio Audio component
        import tempfile
        audio_path = None
        if audio_base64:
            try:
                audio_bytes = base64.b64decode(audio_base64)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                    f.write(audio_bytes)
                    audio_path = f.name
            except Exception as e:
                # If decoding fails, return None for audio path
                audio_path = None

        return audio_path, f"✨ Generated narration:\n\n{generated_text}"

    # Stream version for progressive audio playback
    async def narrate_text_ui_stream(
        prompt: str,
        character: str,
        voice: str,  # Legacy, not used but kept for compatibility
        model: str,
        tts_provider: str,
        unified_voice: str,
    ):
        """Streaming UI wrapper that yields audio chunks as they become available."""
        # Convert empty strings to None
        voice_val = unified_voice.strip() if unified_voice and unified_voice.strip() else None

        # Determine which provider-specific voice parameter to use
        openai_voice_val = None
        elevenlabs_voice_val = None

        if tts_provider == "ElevenLabs TTS":
            elevenlabs_voice_val = voice_val
        else:
            openai_voice_val = voice_val

        # Get API key
        final_llm_api_key = OPENAI_API_KEY
        if not final_llm_api_key:
            yield None, "❌ Error: OPENAI_API_KEY not configured. Please set it in environment variables."
            return

        # Determine TTS provider and API key
        tts_provider_value = None
        if tts_provider == "ElevenLabs TTS":
            tts_provider_value = "elevenlabs"
            final_tts_api_key = ELEVENLABS_API_KEY
            if not final_tts_api_key:
                yield None, "❌ Error: ELEVENLABS_API_KEY not provided."
                return
        else:
            tts_provider_value = "openai"
            final_tts_api_key = final_llm_api_key

        # Handle character
        if character in CHARACTER_CHOICES:
            final_character_id = CHARACTER_CHOICES[character]
        else:
            final_character_id = character or "reluctant_developer"

        # Handle voice
        if tts_provider_value == "elevenlabs":
            if elevenlabs_voice_val:
                from narrator_mcp.characters import get_character
                char_obj = get_character(final_character_id)
                final_voice = char_obj.elevenlabs_voice_id
            else:
                final_voice = None
        else:
            final_voice = openai_voice_val or OPENAI_TTS_VOICE

        try:
            # Create session
            session = Session()
            session.llm_api_key = final_llm_api_key
            session.llm_model = model or DEFAULT_MODEL
            session.voice = final_voice
            session.mode = "narration"
            session.character = final_character_id
            session.tts_api_key = final_tts_api_key
            session.tts_provider = tts_provider_value

            chunker = Chunker(max_tokens=12, sentence_boundary=True)
            ctx = AppContext(session=session, chunker=chunker)

            # Stream narration chunks
            import tempfile
            import time
            accumulated_text = []
            audio_chunks_base64 = []
            chunk_index = 0
            # Use a fixed base timestamp for consistent IDs
            base_timestamp = int(time.time() * 1000000)

            async for text_chunk, audio_chunk in generate_narration_stream(ctx, prompt):
                accumulated_text.append(text_chunk)
                audio_base64 = base64.b64encode(audio_chunk).decode('utf-8')
                audio_chunks_base64.append(audio_base64)
                chunk_index += 1

                # Create HTML with streaming audio player - accumulate all chunks
                full_text = "".join(accumulated_text)

                # Build HTML with all audio chunks so far
                audio_html_parts = []
                for i, (txt_chunk, audio_b64) in enumerate(zip(accumulated_text, audio_chunks_base64)):
                    chunk_audio_id = f"stream-audio-{base_timestamp}-{i+1}"
                    chunk_audio_url = f"data:audio/mpeg;base64,{audio_b64}"
                    audio_html_parts.append(f"""
                    <div id="audio-container-{chunk_audio_id}" style="margin: 10px 0; padding: 10px; border: 1px solid #ddd; border-radius: 4px;">
                        <p style="margin: 0 0 5px 0; font-size: 12px; color: #666;">Chunk {i+1}: "{txt_chunk}"</p>
                        <audio id="{chunk_audio_id}" controls preload="auto" style="width: 100%;">
                            <source src="{chunk_audio_url}" type="audio/mpeg">
                        </audio>
                    </div>
                    """)

                # Latest audio ID matches the last chunk in the loop
                latest_audio_id = f"stream-audio-{base_timestamp}-{chunk_index}"
                audio_html = f"""
                <div id="streaming-audio-container" style="max-height: 400px; overflow-y: auto;">
                    {'<hr style="margin: 10px 0;">'.join(audio_html_parts)}
                </div>
                <script>
                (function() {{
                    // Use setTimeout to ensure DOM is updated
                    setTimeout(function() {{
                        // Auto-play the latest audio chunk
                        const latestAudioId = '{latest_audio_id}';
                        const latestAudio = document.getElementById(latestAudioId);

                        console.log('🎵 Looking for audio:', latestAudioId, 'Found:', latestAudio);

                        if (latestAudio) {{
                            // Stop all other playing audios
                            const allAudios = document.querySelectorAll('#streaming-audio-container audio');
                            allAudios.forEach(a => {{
                                if (a.id !== latestAudioId && !a.paused) {{
                                    console.log('⏹️ Stopping audio:', a.id);
                                    a.pause();
                                    a.currentTime = 0;
                                }}
                            }});

                            // Remove existing event listeners by cloning the element
                            const newAudio = latestAudio.cloneNode(true);
                            latestAudio.parentNode.replaceChild(newAudio, latestAudio);

                            // Auto-play latest when ready
                            newAudio.addEventListener('canplay', function() {{
                                console.log('▶️ Audio can play:', latestAudioId);
                                newAudio.play().catch(e => console.log('Auto-play prevented:', e));
                            }}, {{ once: true }});

                            // Also try to play immediately if already loaded
                            if (newAudio.readyState >= 2) {{
                                console.log('▶️ Audio already loaded, playing immediately');
                                newAudio.play().catch(e => console.log('Auto-play prevented:', e));
                            }}

                            // Load the audio
                            newAudio.load();

                            // Scroll to bottom to show latest chunk
                            const container = document.getElementById('streaming-audio-container');
                            if (container) {{
                                container.scrollTop = container.scrollHeight;
                            }}
                        }} else {{
                            console.warn('⚠️ Audio element not found:', latestAudioId);
                            // Retry after a short delay
                            setTimeout(function() {{
                                const retryAudio = document.getElementById(latestAudioId);
                                if (retryAudio) {{
                                    console.log('✅ Found audio on retry:', latestAudioId);
                                    retryAudio.play().catch(e => console.log('Auto-play prevented:', e));
                                }}
                            }}, 200);
                        }}
                    }}, 100);
                }})();
                </script>
                """

                # Save current accumulated audio to temp file for Gradio Audio component
                # (for compatibility, but streaming HTML will handle playback)
                combined_audio = b''.join([base64.b64decode(chunk) for chunk in audio_chunks_base64])
                temp_audio_path = None
                if combined_audio:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                        f.write(combined_audio)
                        temp_audio_path = f.name

                # Yield progressive updates
                yield (
                    temp_audio_path,
                    f"✨ Streaming narration (chunk {chunk_index}):\n\n{full_text}",
                    audio_html
                )

        except Exception as e:
            import traceback
            error_msg = f"❌ Error: {str(e)}"
            logger.error(f"Narration stream error: {error_msg}\n{traceback.format_exc()}")
            yield None, error_msg, ""

    # Connect the narration handler - use streaming version
    narrate_btn.click(
        fn=narrate_text_ui_stream,
        inputs=[
            prompt_input,
            character_state,
            voice_dropdown,  # Legacy, kept for compatibility but not used
            model_dropdown,
            tts_provider_input,
            voice_dropdown_unified,
        ],
        outputs=[audio_output, text_output, streaming_audio_html],
    )

    # Update UI when TTS provider changes and auto-load voices
    async def async_update_tts_provider(tts_provider: str):
        """Async update UI when TTS provider changes and auto-load voices if needed."""
        if tts_provider == "ElevenLabs TTS":
            # For ElevenLabs, hide voice selection (each character has a fixed voice_id)
            return (
                gr.Group(visible=False),  # openai_tts_group
                gr.Group(visible=True),   # elevenlabs_tts_group
                gr.Dropdown(  # voice_dropdown_unified - hide for ElevenLabs
                    choices=[],
                    value=None,
                    info="Voice is automatically selected based on character",
                    visible=False,  # Hide voice selection for ElevenLabs
                    allow_custom_value=False,
                ),
                "ℹ️ Voice is automatically selected based on the chosen character",
            )
        else:
            # Show OpenAI config, hide ElevenLabs config
            # Update unified voice dropdown with OpenAI voices
            return (
                gr.Group(visible=False),  # openai_tts_group (hidden, voice shown in unified dropdown)
                gr.Group(visible=False),  # elevenlabs_tts_group
                gr.Dropdown(  # voice_dropdown_unified - show OpenAI voices
                    choices=VOICE_OPTIONS,
                    value=OPENAI_TTS_VOICE,
                    info="OpenAI TTS voice selection",
                    visible=True,  # Show voice selection for OpenAI
                    allow_custom_value=False,
                ),
                "",
            )

    # Connect TTS provider change event to show/hide provider configs and load voices
    tts_provider_input.change(
        fn=async_update_tts_provider,
        inputs=[tts_provider_input],
        outputs=[
            openai_tts_group,
            elevenlabs_tts_group,
            voice_dropdown_unified,
            elevenlabs_voice_status,
        ],
    )

    # Expose functions as MCP tools (MCP-only, not shown in UI)
    gr.api(configure)
    gr.api(narrate_text)
    gr.api(list_characters)
    gr.api(get_config_status)

    # Pre-load voices on startup (not needed since voices are hardcoded, but kept for compatibility)
    # Voices are already initialized in the UI, so this is not strictly necessary


# Launch with MCP server enabled
if __name__ == "__main__":
    demo.launch(
        mcp_server=True,
        share=False,
    )
