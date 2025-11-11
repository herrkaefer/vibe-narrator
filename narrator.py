# narration_server.py
import sys
import logging
from mcp.server.fastmcp import FastMCP, Context

# 🪵 Configure logging (output to stderr, avoid polluting stdout)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)]
)

# Create MCP Server
mcp = FastMCP("narrator")

# Register narrate method
@mcp.tool()
def narrate(ctx: Context, text: str) -> dict:
    """
    Echo back the received text.
    Future versions can call LLM + TTS here.
    """
    logging.info(f"🎧 Received narrate() request: {text}")
    # Here it's just a simple echo back, can be extended to stylized and voice output in the future
    return {"echo": text}

if __name__ == "__main__":
    logging.info("🚀 Narration MCP Server starting (STDIO mode)...")
    try:
        mcp.run(transport='stdio')
    except Exception as e:
        logging.exception(f"❌ MCP Server crashed: {e}")
