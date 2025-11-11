# narration_server.py
import sys
import logging
import os
import signal
from pathlib import Path
from datetime import datetime
from mcp.server.fastmcp import FastMCP, Context
import json

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

# 全局变量，用于跟踪是否正在关闭
shutting_down = False

def signal_handler(sig, frame):
    """处理退出信号，记录日志"""
    global shutting_down
    if shutting_down:
        return
    shutting_down = True
    
    signal_name = signal.Signals(sig).name
    logging.info(f"🛑 Received {signal_name} signal, shutting down gracefully...")
    narrate_logger.info(f"🛑 MCP Server shutting down (signal: {signal_name})")
    
    # 发送 shutdown notification 给 client
    try:
        shutdown_notification = {
            "jsonrpc": "2.0",
            "method": "notifications/shutdown",
            "params": {
                "reason": "received_signal",
                "signal": signal_name
            }
        }
        # 直接写入 stdout（MCP Server 的标准输出）
        print(json.dumps(shutdown_notification), flush=True)
        logging.info("📤 Sent shutdown notification to client")
    except Exception as e:
        logging.warning(f"⚠️ Failed to send shutdown notification: {e}")
    
    # 给一点时间让日志和通知写入
    import time
    time.sleep(0.1)
    
    # 退出
    sys.exit(0)

# 注册信号处理
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

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
    except KeyboardInterrupt:
        logging.info("🛑 Interrupted by user (KeyboardInterrupt)")
        narrate_logger.info("🛑 MCP Server interrupted by user")
    except Exception as e:
        logging.exception(f"❌ MCP Server crashed: {e}")
        narrate_logger.error(f"❌ MCP Server crashed: {e}")
    finally:
        if not shutting_down:
            logging.info("🛑 MCP Server shutting down...")
            narrate_logger.info("🛑 MCP Server shutting down (normal exit)")
