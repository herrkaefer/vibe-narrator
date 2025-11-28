# Hugging Face Space Deployment Checklist

## Pre-Deployment Verification

### ✅ Files Ready
- [x] `app.py` - Gradio UI with MCP server integration
- [x] `narrator_mcp/` - Complete MCP server package
- [x] `requirements.txt` - All dependencies listed
- [x] `README.md` - HF Space metadata and documentation
- [x] `logo.png` - Logo image

### ✅ Code Verification
- [x] MCP server imports work: `from narrator_mcp.server import mcp`
- [x] Gradio app loads successfully
- [x] All relative imports fixed (using `.` prefix)
- [x] MCP server launch parameter: `demo.launch(mcp_server=True)`

### ✅ Dependencies
```
gradio==6.0.1
fastmcp>=0.1.0
openai>=1.0.0
httpx
python-dotenv
```

## Deployment Steps

### 1. Create Hugging Face Space

1. Go to https://huggingface.co/new-space
2. Fill in:
   - **Space name**: `vibe-narrator` (or your choice)
   - **License**: MIT
   - **SDK**: Gradio
   - **SDK version**: 6.0.1
   - **Hardware**: Free CPU (default)

### 2. Upload Files

Upload the entire `hfspace/` folder contents:
```
hfspace/
├── app.py
├── narrator_mcp/
│   ├── __pycache__/
│   ├── characters.py
│   ├── chunker.py
│   ├── llm.py
│   ├── logs/
│   ├── pyproject.toml
│   ├── server.py
│   ├── session.py
│   ├── tests/
│   ├── tts.py
│   └── uv.lock
├── logo.png
├── README.md
├── requirements.txt
└── DEPLOYMENT.md (this file)
```

**Methods**:
- Git: Push to the Space's Git repository
- Web UI: Upload files via Hugging Face web interface
- CLI: Use `huggingface-cli upload`

### 3. Configure Environment Variables

**Required**:
- Settings → Repository secrets
- Add secret: `OPENAI_API_KEY` with your OpenAI API key

**Optional**:
- Add secret: `ELEVENLABS_API_KEY` for ElevenLabs TTS support

These secrets will be available as environment variables to the app.

### 4. Build and Deploy

HF Spaces will automatically:
1. Detect `app.py` as entry point
2. Install dependencies from `requirements.txt`
3. Launch with `python app.py`
4. Enable MCP server at `/gradio_api/mcp/sse`

### 5. Verify Deployment

Check these after deployment:

1. **Web UI loads**: Visit your Space URL
2. **Tabs work**: Narrate, Characters, MCP Server, About
3. **MCP endpoint**: Check footer for "View API" → "MCP"
4. **Environment variables set**: Check Settings → Repository secrets
5. **Test narration**:
   - Add test text
   - Select character
   - Select TTS provider
   - Click "Generate Narration"

## Post-Deployment

### MCP Client Connection

Update your MCP client config with your actual Space URL:

```json
{
  "mcpServers": {
    "narrator-mcp": {
      "url": "https://YOUR-USERNAME-vibe-narrator.hf.space/gradio_api/mcp/sse"
    }
  }
}
```

Replace:
- `YOUR-USERNAME` with your HF username
- `vibe-narrator` with your Space name (if different)

### Test MCP Connection

1. Restart Claude Desktop (or your MCP client)
2. Check MCP connection status
3. Test with: "Narrate this text: Hello world"
4. MCP server will use environment variables for API keys automatically

## Troubleshooting

### Build Fails

Check build logs:
- Settings → Build logs
- Look for missing dependencies
- Verify Python version compatibility (requires Python 3.11+)

### Import Errors

Ensure all imports in `narrator_mcp/` use relative imports:
```python
from .characters import ...  # ✅ Correct
from characters import ...   # ❌ Wrong
```

### MCP Not Available

Check:
1. `app.py` has `demo.launch(mcp_server=True)`
2. `from narrator_mcp.server import mcp` succeeds
3. Gradio version is 6.0.1+

### Runtime Errors

Check application logs:
- Settings → Application logs
- Look for Python exceptions
- Verify all dependencies installed

## Local Testing Before Deployment

Test locally before deploying:

```bash
cd hfspace/

# Set environment variables
export OPENAI_API_KEY="your-key-here"
export ELEVENLABS_API_KEY="your-key-here"  # Optional

# Install and run
pip install -r requirements.txt
python app.py
```

Visit http://localhost:7860 and test:
- UI loads
- Configuration sections render
- Character selection works
- Narration generates audio (with env vars set)

## Updates After Deployment

To update the Space:

1. **Git method**:
   ```bash
   git add .
   git commit -m "Update message"
   git push
   ```

2. **Web UI**: Upload updated files

3. **Space rebuilds automatically**

## Performance Notes

### Free CPU Tier
- Sufficient for demo and light usage
- May be slow for multiple concurrent narrations
- Consider upgrading for production use

### Persistent Storage
- `narrator_mcp/logs/` will be cleared on restart
- No persistent storage on free tier
- Sessions are per-user, not shared

## Security

### Environment Variables
- API keys are stored as HF Spaces secrets
- Keys are loaded from environment variables at runtime
- Not exposed to users in the UI
- All processing happens server-side
- Keys are managed through HF Spaces Settings

### Private Space Option
If you make the Space private:
- Add Bearer token to MCP client config:
```json
{
  "mcpServers": {
    "narrator-mcp": {
      "url": "https://YOUR-SPACE.hf.space/gradio_api/mcp/sse",
      "headers": {
        "Authorization": "Bearer YOUR_HF_TOKEN"
      }
    }
  }
}
```

## Success Indicators

✅ Space builds successfully
✅ Web UI is accessible
✅ All tabs render correctly
✅ MCP endpoint appears in API docs
✅ External MCP clients can connect
✅ Environment variables configured
✅ Narration generates audio

## Additional Resources

- [Gradio Spaces Docs](https://huggingface.co/docs/hub/spaces-overview)
- [Gradio MCP Integration](https://huggingface.co/blog/gradio-mcp)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [Project Repository](https://github.com/herrkaefer/vibe-narrator)

---

**Ready to Deploy!** 🚀

The `hfspace/` folder is now ready to be uploaded to Hugging Face Spaces.
