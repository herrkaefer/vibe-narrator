---
title: Vibe Narrator
emoji: 🎨
colorFrom: indigo
colorTo: pink
sdk: gradio
sdk_version: 6.0.1
app_file: app.py
pinned: false
license: mit
short_description: Agents talk with personality while coding for you.
tags:
  - building-mcp-track-creative
  - text-to-speech
  - mcp-server
  - voice-ai
---

# 🎨 Vibe Narrator

**Stylized voice embodiment for terminal agents. Give your code a voice with personality!**

Vibe Narrator transforms text into narrated speech with distinct character personalities, combining LLM interpretation with text-to-speech generation. Perfect for giving your AI agents, code documentation, or terminal output a unique voice.

## Features

- **6 Unique Character Personalities** - From burned-out developers to zen masters
- **Dual Modes** - Narration (retelling) or Chat (conversation)
- **MCP Server Integration** - Use as a standalone service or integrate with Claude Desktop
- **Gradio Web UI** - Easy-to-use interface for quick narration
- **OpenAI & ElevenLabs Support** - Choose your TTS provider

## Quick Start

### Using the Web Interface

1. Type or paste text to narrate
2. Select a character personality (Style section)
3. Choose LLM model (default: gpt-4o-mini)
4. Select TTS provider and voice
5. Click "Generate Narration"

**Note**: API keys are configured via environment variables (OPENAI_API_KEY, ELEVENLABS_API_KEY)

### Characters

- **The Burned-Out Developer** - Flat, drained, deeply unenthusiastic
- **The Overconfident Senior Developer** - Energetic, smug, wrong about everything
- **The Reluctant Developer** - Exhausted, unmotivated, begrudgingly compliant
- **The Enlightened Zen Developer** - Calm, serene, meditative
- **The Adoring Fanboy** - Extremely enthusiastic, worshipful
- **The Whispering ASMR Developer** - Soft, intimate, soothing

## MCP Server

This Space also exposes an MCP (Model Context Protocol) server that can be used by external clients like Claude Desktop.

### MCP Endpoint

```
https://mcp-1st-birthday-vibe-narrator.hf.space/gradio_api/mcp/sse
```

### Client Configuration

Add this to your MCP client configuration (e.g., `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

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

<div style="display: flex; gap: 20px;">
<div style="flex: 1;">

- `configure` - Set up API keys and narration settings
- `narrate` - Generate narrated speech with personality
- `list_characters` - Get available character personalities
- `get_config_status` - Check current configuration

</div>
<div style="flex: 1;">

![Architecture](structure.jpeg)

</div>
</div>

### Example MCP Usage

Once connected to Claude Desktop:

```
User: Configure the narrator with my API key sk-... and use the zen_developer character

Claude: [Calls configure tool]

User: Narrate this text: "The code compiled successfully on the first try."

Claude: [Calls narrate tool and returns audio + text]
```

## How It Works

1. **LLM Interpretation** - GPT processes your text through a character's personality filter
2. **Streaming Generation** - Text is generated token-by-token with character-specific prompts
3. **TTS Conversion** - Generated text is converted to speech using OpenAI or ElevenLabs TTS
4. **Character Voice** - TTS instructions ensure the voice matches the character's personality

## Technical Details

### Architecture

- **Gradio Frontend** - Web UI for direct interaction
- **FastMCP Backend** - MCP protocol server for external clients
- **Dual Transport** - SSE for remote access, stdio for local development
- **Async Streaming** - LLM and TTS run concurrently for low latency

### Environment Variables

Required:
- `OPENAI_API_KEY` - For GPT model (LLM) and OpenAI TTS

Optional:
- `ELEVENLABS_API_KEY` - For ElevenLabs TTS (alternative to OpenAI TTS)

### Models

- Default: `gpt-4o-mini` (fast and economical)
- Also supports: `gpt-4o`, `gpt-4-turbo`, `gpt-3.5-turbo`

### Voices

OpenAI TTS voices available: `alloy`, `echo`, `fable`, `onyx`, `nova`, `shimmer`

## Modes Explained

### Narration Mode

Re-narrates the input content in the character's voice, interpreting and expressing it with their personality. Best for:
- Reading code documentation
- Terminal output narration
- Status updates

### Chat Mode

Responds to questions with the character's personality. Best for:
- Conversational AI agents
- Interactive Q&A
- Personality-driven assistance

## Local Development

For local development and testing, see the main repository:

**GitHub**: https://github.com/herrkaefer/vibe-narrator

## Use Cases

- Terminal agent voice personality
- Code documentation narration
- AI assistant character embodiment
- Creative content generation
- Accessibility (text-to-speech with flair)
- Entertainment and humor

## Privacy & Security

- API keys are configured via environment variables on the server
- All processing happens server-side
- Audio is generated on-demand
- No user data persistence
- Sessions are isolated

## Credits

Built with:
- [Gradio](https://gradio.app/) - Web UI framework
- [FastMCP](https://github.com/jlowin/fastmcp) - MCP server implementation
- [OpenAI](https://openai.com/) - LLM and TTS
- [Hugging Face Spaces](https://huggingface.co/spaces) - Free hosting

## Social Media

Follow the project on X (Twitter): [@herr_kaefer](https://x.com/herr_kaefer/status/1995047657434145103)

## License

MIT License - See repository for details

## Contributing

Contributions welcome! Visit the GitHub repository to:
- Report issues
- Suggest new characters
- Improve voice instructions
- Add features

---

**Note**: This Space requires `OPENAI_API_KEY` environment variable to be set. Optionally set `ELEVENLABS_API_KEY` for ElevenLabs TTS support.
