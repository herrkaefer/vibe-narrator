<img src="logo.png" alt="logo" width="240"/>

## Structure

### Narrator MCP Server

The narrator MCP server (`narrator-mcp/server.py`) is implemented using the **official MCP Python SDK** and provides three standard MCP tools:

1. **`configure`** - Configure API credentials and narration settings (API key, model, voice, mode, character)
2. **`narrate`** - Convert text to narrated speech using LLM + TTS (returns generated text and base64-encoded MP3 audio)
3. **`list_characters`** - List available character personalities

**Key Features:**
- ✅ 100% standard MCP protocol (no custom extensions)
- ✅ Session-based configuration (configure once, narrate multiple times)
- ✅ Stateful session management via MCP SDK lifespan context
- ✅ Supports OpenAI and OpenRouter APIs
- ✅ Character-based personality system (5 built-in characters)
- ✅ Comprehensive logging

### Bridge Client

The bridge client (`bridge.py`) uses the **official MCP client SDK** to:

1. Spawn the MCP server as a subprocess
2. Initialize MCP protocol connection
3. Configure the server with API credentials
4. Run a command in a PTY (pseudo-terminal)
5. Buffer terminal output and send chunks to the narrate tool
6. Play returned audio in real-time

**Key Features:**
- ✅ Async/await architecture using official MCP client
- ✅ PTY integration for capturing command output
- ✅ Smart text buffering (accumulates output before narration)
- ✅ Real-time audio playback
- ✅ ANSI escape sequence cleaning

## Why is this implemented as an MCP server?

So that it can serve as a general purpose MCP server, not just for coding agents or local usage. The standard MCP protocol means it can integrate with any MCP-compatible client (Claude Desktop, custom applications, etc.).

## Why is the bridge needed?

Without the bridge, you would need to manually call the MCP tools from your application. The bridge automates this by:

- Capturing terminal output from any command (e.g., `claude`, `python`, `bash`)
- Automatically buffering and sending text chunks for narration
- Playing audio in real-time without requiring manual intervention

This makes narration seamless and hands-free during interactive coding sessions.

## License

MIT License
