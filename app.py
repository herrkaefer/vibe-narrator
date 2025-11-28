"""Vibe Narrator - Gradio UI with MCP Server Integration"""

import gradio as gr
import base64
import json
import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file (if exists)
# This won't override existing environment variables (e.g., from Space settings)
load_dotenv()

# Import underlying functions and classes
from narrator_mcp.server import generate_narration, AppContext
from narrator_mcp.characters import get_characters_list
from narrator_mcp.session import Session, DEFAULT_MODEL, DEFAULT_VOICE, DEFAULT_MODE
from narrator_mcp.chunker import Chunker
from narrator_mcp.tts import detect_tts_provider

# Get API keys from environment
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

# Get available characters
CHARACTERS = get_characters_list()
CHARACTER_CHOICES = {f"{char['name']}": char['id'] for char in CHARACTERS}
DEFAULT_CHARACTER = "The Reluctant Developer"

# Voice options (OpenAI TTS voices)
VOICE_OPTIONS = ["nova", "alloy", "echo", "fable", "onyx", "shimmer"]

# TTS Provider options
TTS_PROVIDER_OPTIONS = ["OpenAI TTS", "ElevenLabs TTS"]

# Model options
MODEL_OPTIONS = ["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"]

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
) -> tuple[str | None, str]:
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
        return None, "Please enter some text to narrate."

    global _global_session, _global_context

    # Determine API keys (prefer parameters, then session, then environment variables)
    final_llm_api_key = llm_api_key or _global_session.llm_api_key or OPENAI_API_KEY
    if not final_llm_api_key:
        return None, "Error: OPENAI_API_KEY not provided. Please configure using configure tool or set environment variable."

    # Use session defaults if parameters not provided
    final_model = model or _global_session.llm_model
    final_voice = voice or _global_session.voice
    final_mode = "narration"  # Fixed to narration mode for UI
    final_character_id = None

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

    # Determine TTS provider and API key
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

    # Determine TTS API key
    if not final_tts_api_key:
        if tts_provider_value == "elevenlabs":
            final_tts_api_key = _global_session.tts_api_key or ELEVENLABS_API_KEY
            if not final_tts_api_key:
                return None, "Error: ELEVENLABS_API_KEY not provided. Please configure using configure tool or set environment variable."
        else:
            # Use LLM API key for TTS if TTS key not provided
            final_tts_api_key = _global_session.tts_api_key or final_llm_api_key

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

        # Save to temporary file for Gradio
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
            f.write(audio_bytes)
            audio_path = f.name

        return audio_path, f"✨ Generated narration:\n\n{text}"

    except Exception as e:
        error_msg = f"❌ Error generating narration: {str(e)}"
        return None, error_msg


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


# Create the Gradio interface
with gr.Blocks(title="Vibe Narrator - Stylized Voice Embodiment") as demo:
    gr.Markdown("# 🎨 Vibe Narrator")
    gr.Markdown("Stylized voice embodiment for terminal agents. Give your code a voice with personality!")

    # Display logo if available
    logo_path = Path(__file__).parent / "logo.png"
    if logo_path.exists():
        gr.Image(str(logo_path), show_label=False, container=False, height=120)

    with gr.Tabs():
        # Main Narration Tab
        with gr.Tab("Narrate"):
            with gr.Row():
                with gr.Column(scale=1):
                    gr.Markdown("## 📝 Input")

                    prompt_input = gr.Textbox(
                        label="Text to Narrate",
                        placeholder="Enter the text you want to narrate...",
                        lines=8,
                        value="",
                    )

                    gr.Markdown("## ⚙️ Configuration")

                    with gr.Accordion("Style", open=True):
                        character_dropdown = gr.Dropdown(
                            label="Character Personality",
                            choices=list(CHARACTER_CHOICES.keys()),
                            value=DEFAULT_CHARACTER,
                            info="Choose the voice personality",
                        )

                    with gr.Accordion("LLM Model", open=True):
                        model_dropdown = gr.Dropdown(
                            label="Model",
                            choices=MODEL_OPTIONS,
                            value=DEFAULT_MODEL,
                            info="GPT model for text generation",
                        )

                    with gr.Accordion("TTS (Text-to-Speech)", open=True):
                        tts_provider_input = gr.Dropdown(
                            label="TTS Provider",
                            choices=TTS_PROVIDER_OPTIONS,
                            value="OpenAI TTS",
                            info="Choose TTS service provider",
                        )

                        voice_dropdown = gr.Dropdown(
                            label="Voice",
                            choices=VOICE_OPTIONS,
                            value=DEFAULT_VOICE,
                            info="TTS voice selection",
                        )

                    narrate_btn = gr.Button("🎤 Generate Narration", variant="primary", size="lg")

                with gr.Column(scale=1):
                    gr.Markdown("## 🎵 Output")

                    audio_output = gr.Audio(
                        label="Generated Audio",
                        type="filepath",
                        interactive=False,
                    )

                    text_output = gr.Textbox(
                        label="Generated Text",
                        lines=12,
                        interactive=False,
                    )

        # Characters Info Tab
        with gr.Tab("Characters"):
            gr.Markdown("## Available Characters")
            gr.Markdown(get_character_info())

            gr.Markdown("""
            ### Character Personalities

            - **The Burned-Out Developer**: Flat, drained, deeply unenthusiastic - debugging fatigue incarnate
            - **The Overconfident Senior Developer**: Energetic, smug, wrong about everything but says it with authority
            - **The Reluctant Developer**: Exhausted, unmotivated, begrudgingly compliant - every sentence sounds forced
            - **The Enlightened Zen Developer**: Calm, serene, meditative - code is a path to enlightenment
            - **The Adoring Fanboy**: Extremely enthusiastic, worshipful - every line of code is a masterpiece
            - **The Whispering ASMR Developer**: Soft, intimate, soothing - code explained with ASMR-like tranquility
            """)

        # MCP Info Tab
        with gr.Tab("MCP Server"):
            gr.Markdown("## MCP Server Information")
            gr.Markdown("""
            This Gradio app also exposes an MCP (Model Context Protocol) server that can be used by external clients.

            ### MCP Endpoint

            When deployed on Hugging Face Spaces, the MCP server is available at:
            ```
            https://YOUR-USERNAME-vibe-narrator.hf.space/gradio_api/mcp/sse
            ```

            ### Client Configuration

            Add this to your MCP client configuration (e.g., Claude Desktop):

            ```json
            {
              "mcpServers": {
                "narrator-mcp": {
                  "url": "https://YOUR-USERNAME-vibe-narrator.hf.space/gradio_api/mcp/sse"
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

    # Connect the narration handler
    narrate_btn.click(
        fn=narrate_text,
        inputs=[
            prompt_input,
            character_dropdown,
            voice_dropdown,
            model_dropdown,
            tts_provider_input,
        ],
        outputs=[audio_output, text_output],
    )

    # Expose functions as MCP tools (MCP-only, not shown in UI)
    gr.api(configure)
    gr.api(narrate_text)
    gr.api(list_characters)
    gr.api(get_config_status)


# Launch with MCP server enabled
if __name__ == "__main__":
    demo.launch(
        mcp_server=True,
        share=False,
    )
