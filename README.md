---
title: Vibe Narrator
emoji: 🎭
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

<img src="assets/logo.png" alt="logo" height="128"/>

# 🎭 Vibe Narrator

**Stylized voice embodiment for terminal agents. Give your code a voice with personality!**

Vibe Narrator transforms text into narrated speech with distinct character personalities, combining LLM interpretation with text-to-speech generation. Perfect for giving your AI agents, code documentation, or terminal output a unique voice.

## Features

- **Unique Character Personalities** - From burned-out developers to zen masters
- **Dual Modes** - Narration (retelling) or Chat (conversation)
- **MCP Server Integration** - Use as a standalone service or integrate with Claude Desktop
- **Gradio Web UI** - Easy-to-use interface for quick narration
- **OpenAI & ElevenLabs Support** - Choose your TTS provider

## Quick Start

### Local Installation & Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/herrkaefer/vibe-narrator.git
   cd vibe-narrator
   ```

2. **Install dependencies**

   Sync dependencies:
   ```bash
   cd terminal_client
   uv sync
   ```

3. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env and add your OPENAI_API_KEY, LLM_MODEL, TTS_VOICE, TTS_PROVIDER, etc.
   ```

4. **Set script permissions**
   ```bash
   chmod +x terminal_client/narrate
   ```

5. **Create a shortcut (optional, for global access)**

   ```bash
   # Add to your ~/.zshrc or ~/.bashrc
   alias narrate='$(path-to-vibe-narrator)/terminal_client/narrate'

   # Then reload your shell
   source ~/.zshrc  # or source ~/.bashrc
   ```

6. **Run with your agent**
   ```bash
   narrate codex
   # or
   narrate claude
   # or
   narrate gemini
   ```

### Characters

- **The Burned-Out Developer** - Flat, drained, deeply unenthusiastic
- **The Overconfident Senior Developer** - Energetic, smug, wrong about everything
- **The Reluctant Developer** - Exhausted, unmotivated, begrudgingly compliant
- **The Enlightened Zen Developer** - Calm, serene, meditative
- **The Adoring Fanboy** - Extremely enthusiastic, worshipful
- **The Whispering ASMR Developer** - Soft, intimate, soothing
- (More to add...)

## MCP Server

This Gradio app also exposes an MCP (Model Context Protocol) server that can be used by external clients like Claude Desktop.

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

### System Architecture

![System Architecture](assets/structure.jpeg)

## How It Works

### 🔄 Vibe Narrator MCP Server

Narrator-mcp is a standard MCP server that can be deployed either locally or on a remote server.

It provides the following tools:

- **configure**: Set up API keys and narration settings
- **narrate_text**: Generate narrated speech with personality
- **list_characters**: Get available character personalities
- **get_config_status**: Check current configuration status

It can be used with any MCP client.

### 🔌 Bridge Tool

#### Let terminal agents talk while coding

The bridge tool (`terminal_client/bridge.py`) is a Python script that helps:

- **Capture terminal output**: Uses PTY to capture stdout/stderr from any command
- **Clean terminal output**: Removes terminal formatting codes for clean text
- **Buffer terminal output**: Accumulates output before sending for narration
- **Connect to MCP server**: Uses the official MCP client SDK to communicate with the narrator server
- **Play audio**: Handles real-time audio playback as narration is generated

A `narrate` script is provided to help you start the bridge tool with a command:

**Usage Example:**
```bash
narrate codex | claude | gemini | ...
```

This runs the agent with narration enabled.

### 🌐 Compatibility

#### Terminal Agent Compatibility

Vibe Narrator is a standard MCP server that can be used with any MCP client.

The terminal client `bridge.py` is compatible with many terminal-based agents: codex, Claude Code, Gemini, etc.

**Why MCP?**
- Standard protocol for AI tool integration
- Works across different platforms and agents

## Technical Details

### Architecture

- **Gradio Frontend** - Web UI for direct interaction
- **MCP Server Backend** - Standard MCP protocol server for external clients
- **Dual Transport** - SSE for remote access, stdio for local development
- **Async Streaming** - LLM and TTS run concurrently for low latency
- **Bridge Tool** - Terminal client that captures output and connects to MCP server

### Environment Variables

Required:
- `OPENAI_API_KEY` - For GPT model (LLM) and OpenAI TTS

Optional:
- `ELEVENLABS_API_KEY` - For ElevenLabs TTS (alternative to OpenAI TTS)

### Models

**Supported LLM Providers:**
- OpenAI
- OpenRouter

**Model Options:**
- Default: `gpt-4o-mini` (fast and economical)
- Also supports: `gpt-4o`, `gpt-5`, `gpt-5.1`

Note: When using OpenRouter, configure `base_url` and `default_headers` via the `configure` tool or environment variables.

### Voices

OpenAI TTS voices available: `alloy`, `ash`, `ballad`, `coral`, `echo`, `fable`, `nova`, `onyx`, `sage`, `shimmer`

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
- [MCP](https://modelcontextprotocol.io/) - Model Context Protocol for AI tool integration
- [OpenAI](https://openai.com/) - LLM and TTS
- [ElevenLabs](https://elevenlabs.io/) - Alternative TTS provider
- [Hugging Face Spaces](https://huggingface.co/spaces) - Free hosting
- [OpenRouter](https://openrouter.ai/) - Alternative LLM provider

## Social Media

Follow the project on X (Twitter): [@herr_kaefer](https://x.com/herr_kaefer/status/1995168703785079174)

## License

MIT License - See repository for details
