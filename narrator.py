# narration_server.py
import sys
import logging
import os
from pathlib import Path
from datetime import datetime
from mcp.server.fastmcp import FastMCP, Context

# 获取脚本目录，用于存放日志文件
script_dir = Path(__file__).parent.absolute()
log_dir = script_dir / "logs"
os.makedirs(log_dir, exist_ok=True)

# 创建专门的日志文件用于记录接收到的文本
narrate_log_file = log_dir / f"narrator_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# 🪵 Configure logging (output to stderr, avoid polluting stdout)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)]
)

# 创建文件日志处理器，用于记录接收到的文本
file_handler = logging.FileHandler(narrate_log_file, encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(file_formatter)

# 创建专门的 logger 用于记录 narrate 请求
narrate_logger = logging.getLogger("narrate")
narrate_logger.addHandler(file_handler)
narrate_logger.setLevel(logging.INFO)

# Create MCP Server
mcp = FastMCP("narrator")

# Register narrate method
@mcp.tool()
def narrate(ctx: Context, text: str) -> dict:
    """
    Log the received text to a log file.
    Future versions can call LLM + TTS here.
    """
    logging.info(f"🎧 Received narrate() request: {text}")
    # 将文本记录到日志文件
    narrate_logger.info(f"📝 Narrate text:\n{text}")
    # 返回确认消息
    return {"status": "ok"}

if __name__ == "__main__":
    logging.info("🚀 Narration MCP Server starting (STDIO mode)...")
    logging.info(f"📝 Narrate logs will be written to: {narrate_log_file}")
    try:
        mcp.run(transport='stdio')
    except Exception as e:
        logging.exception(f"❌ MCP Server crashed: {e}")
