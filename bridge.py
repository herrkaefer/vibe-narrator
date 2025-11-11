# bridge.py
import subprocess
import json
import threading
import sys
import time
import logging
import os
import re
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler

# 获取脚本目录，用于存放日志文件
script_dir = Path(__file__).parent.absolute()
log_file = script_dir / "logs" / f"bridge_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
os.makedirs(script_dir / "logs", exist_ok=True)

# 配置 logging 输出到文件
logging.basicConfig(
    level=logging.INFO,  # Can be changed to DEBUG to see details
    format="%(asctime)s [%(levelname)s] %(threadName)s: %(message)s",
    handlers=[
        RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,  # 保留5个备份文件
            encoding='utf-8'
        )
    ]
)
logger = logging.getLogger(__name__)
logger.info(f"📝 Logging to file: {log_file}")


class MCPBridge:
    def __init__(self, server_cmd=None):
        # Get the directory where this script is located
        script_dir = Path(__file__).parent.absolute()
        narrator_path = script_dir / "narrator.py"

        # Use default command if not provided
        if server_cmd is None:
            server_cmd = ["python", str(narrator_path)]

        logger.info(f"🚀 Starting MCP Server subprocess...")
        logger.info(f"📁 Script directory: {script_dir}")
        logger.info(f"📄 Narrator path: {narrator_path}")

        self.proc = subprocess.Popen(
            server_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=str(script_dir)  # Set working directory to script's directory
        )
        logger.info(f"✅ MCP Server process started (PID: {self.proc.pid})")

        # Synchronization mechanism for waiting for initialize response
        self.initialize_event = threading.Event()
        self.initialize_response = None

        # Track pending requests to wait for responses
        self.pending_requests = {}  # id -> timestamp
        self.responses_received = {}  # id -> response

        # Listening threads
        threading.Thread(target=self._listen_stdout, name="ServerStdout", daemon=True).start()
        threading.Thread(target=self._listen_stderr, name="ServerStderr", daemon=True).start()

        # Initialize handshake - requires correct MCP parameters
        self._send({
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "bridge",
                    "version": "1.0.0"
                }
            }
        })
        logger.info("🤝 Sent MCP initialize request")

        # Wait for initialize response then send initialized notification
        if self.initialize_event.wait(timeout=5.0):
            logger.info("✅ Received initialize response, sending initialized notification")
            self._send({
                "jsonrpc": "2.0",
                "method": "notifications/initialized"
            })
            logger.info("✅ Sent initialized notification")
        else:
            logger.error("❌ Timeout waiting for initialize response")

    def _send(self, msg: dict):
        """Send JSON-RPC request to MCP Server"""
        try:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
            logger.debug(f"➡️ Sent to MCP Server: {msg}")
        except Exception as e:
            logger.exception(f"❌ Failed to send message: {e}")

    def _listen_stdout(self):
        """Listen to MCP Server's stdout (JSON responses)"""
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                logger.info(f"🟢 MCP Server Response: {line}")
                msg = json.loads(line)

                # Check if it's an initialize response (id=0)
                if msg.get("id") == 0 and "result" in msg:
                    self.initialize_response = msg
                    self.initialize_event.set()
                    logger.info(f"✅ Received initialize response: {msg.get('result', {})}")

                # Track tool call responses
                response_id = msg.get("id")
                if response_id is not None:
                    self.responses_received[response_id] = msg
                    if response_id in self.pending_requests:
                        del self.pending_requests[response_id]
                    logger.info(f"🟢 MCP Server Response (id={response_id}): {msg}")

            except json.JSONDecodeError:
                logger.warning(f"⚠️ Non-JSON output from MCP Server: {line}")

    def _listen_stderr(self):
        """Listen to MCP Server's stderr (logs)"""
        for line in self.proc.stderr:
            logger.debug(f"🔴 MCP Server Log: {line.strip()}")

    def send_chunk(self, text):
        """Send text chunks to MCP Server - use tools/call to call tool"""
        req = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000),
            "method": "tools/call",
            "params": {
                "name": "narrate",
                "arguments": {
                    "text": text
                }
            }
        }
        self.pending_requests[req["id"]] = time.time()
        self._send(req)
        logger.info(f"📤 Sent text chunk to MCP Server:\n{text}")

    def wait_for_responses(self, timeout=5.0):
        """Wait for all pending requests to receive responses"""
        start_time = time.time()
        while self.pending_requests and (time.time() - start_time) < timeout:
            time.sleep(0.1)
        if self.pending_requests:
            logger.warning(f"⚠️ Still waiting for {len(self.pending_requests)} responses: {list(self.pending_requests.keys())}")


def clean_ansi_codes(text: str) -> str:
    """
    清理 ANSI 转义序列（颜色代码、格式化字符等），还原纯文本

    移除的 ANSI 序列包括：
    - 颜色代码：\x1b[30m - \x1b[37m (前景色), \x1b[40m - \x1b[47m (背景色)
    - 样式代码：\x1b[0m (重置), \x1b[1m (粗体), \x1b[2m (暗淡), 等
    - 光标控制：\x1b[K (清除到行尾), \x1b[J (清除屏幕), 等
    - DEC 私有模式序列：\x1b[?数字h/l (如 [?25l, [?2004h 等)
    - OSC 序列：\x1b]数字;...\x07 或 \x1b]数字;...\x1b\\ (如 ]0;title, ]9;command)
    - 通用格式：\x1b[...m 或 \033[...m

    Args:
        text: 包含 ANSI 转义序列的文本

    Returns:
        清理后的纯文本
    """
    if not text:
        return text

    # 移除 OSC (Operating System Command) 序列
    # 完整格式：\x1b]数字;文本\x07 或 \x1b]数字;文本\x1b\\
    # 但可能被分割，只剩下 ]数字;文本 或 ]数字;
    osc_patterns = [
        r'\x1b\]\d+;.*?(\x07|\x1b\\)',  # 完整的 OSC 序列（带前缀）
        r'\033\]\d+;.*?(\x07|\x1b\\)',  # 八进制形式
        r'\]\d+;.*?(\x07|\x1b\\)',      # 前缀已移除的 OSC 序列（带结尾）
        r'\]\d+;[^\n]*',                 # 前缀和结尾都移除的 OSC 序列（]数字;后面到行尾）
    ]

    # 移除所有 ANSI 转义序列（包括 DEC 私有模式和 OSC）
    ansi_patterns = [
        r'\x1b\[[0-9;]*[a-zA-Z]',           # 标准 ANSI 序列
        r'\x1b\[[?][0-9;]*[hHlL]',          # DEC 私有模式序列
        r'\033\[[0-9;]*[a-zA-Z]',            # 标准 ANSI 序列（八进制）
        r'\033\[[?][0-9;]*[hHlL]',           # DEC 私有模式序列（八进制）
        r'\[[?][0-9;]*[hHlL]',               # 单独的 DEC 私有模式序列
        r'\[[0-9;]*[a-zA-Z]',                 # 单独的 ANSI 序列
        r'\[[0-9;]+',                         # 不完整的 ANSI 序列（如 [38;2;102;102）
        r'^[;0-9]+m',                         # 序列的继续部分（如 ;102m）
    ] + osc_patterns

    # 组合所有模式
    ansi_escape = re.compile('|'.join(ansi_patterns))
    text = ansi_escape.sub('', text)

    # 移除其他常见的控制字符（但保留换行符、制表符等有用的）
    # 移除退格、回车（单独出现时）、响铃等
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

    # 移除乱码字符（替换字符 U+FFFD）
    text = text.replace('\ufffd', '')
    # 移除其他无效的 Unicode 字符
    text = re.sub(r'[\u200b-\u200f\u202a-\u202e\ufeff]', '', text)

    return text


import unicodedata

def filter_ui_elements(text: str) -> str:
    """
    只保留自然语言字符，过滤掉所有特殊字符、图标、UI 元素等

    支持所有人类语言：中文、日语、法语、德语、英语等
    """
    if not text:
        return ""

    lines = text.split('\n')
    filtered_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 1. 过滤用户输入（以 > 开头的行）
        if line.startswith('>'):
            continue

        # 2. 过滤以问号开头的 Claude Code 提示（如 "? for shortcuts"）
        if line.startswith('?'):
            continue

        # 3. 过滤 OSC 序列残留（如 "]0; Display Circle", "]9;"）
        if re.match(r'^\]\d+;', line.strip()):
            continue

        # 4. 过滤 UI 提示文本
        ui_patterns = [
            r'^Thinking on \(tab to toggle\)',
            r'^\(esc to interrupt\)',
            r'^\(esc to interrupt',
            r'^Thought for \d+s',
            r'^ctrl\+o to show thinking',
            r'^ctrlo to show thinking',
            r'^Tip: Type',
            r'^Showing detailed transcript',
            r'^CtrlO to toggle',
            r'^accept edits on',
            r'^shift\+tab to cycle',
            r'^ctrl-g to edit prompt in vi',
        ]
        if any(re.match(pattern, line, re.IGNORECASE) for pattern in ui_patterns):
            continue

        # 5. 过滤分隔线（主要是 - 或 = 的长行）
        if len(line) > 20:
            line_chars = set(line.replace(' ', ''))
            separator_chars = set('-=─━')
            if line_chars.issubset(separator_chars) or \
               (len(line_chars & separator_chars) > 0 and len(line_chars - separator_chars) <= 2):
                continue

        # 6. 只保留自然语言字符
        filtered_chars = []
        for char in line:
            cat = unicodedata.category(char)

            # 保留所有字母（L* = Letter，包括所有语言）
            if cat.startswith('L'):
                filtered_chars.append(char)
            # 保留所有数字（N* = Number）
            elif cat.startswith('N'):
                filtered_chars.append(char)
            # 保留空格（Zs = Space Separator）
            elif cat == 'Zs':
                filtered_chars.append(char)
            # 保留竖线字符（显式保留，确保不被过滤）
            elif char == '|':
                filtered_chars.append(char)
            # 保留常见文本标点（P* = Punctuation，但需要筛选）
            elif cat.startswith('P'):
                # 保留常见标点符号
                if char in '.,!?;:\'"()[]{}-_/\\@#$%&*+=<>|~`^…—–«»„"':
                    filtered_chars.append(char)
                # 保留中文标点范围
                elif '\u3000' <= char <= '\u303f' or '\uff00' <= char <= '\uffef':
                    filtered_chars.append(char)
            # 暂时保留分隔线字符（用于检查模式）
            elif char in '-=─━':
                filtered_chars.append(char)
            # 暂时保留 > 字符（用于检查用户输入）
            elif char == '>':
                filtered_chars.append(char)

        line = ''.join(filtered_chars)

        # 7. 清理多余空白
        line = re.sub(r'\s+', ' ', line).strip()

        if line:
            filtered_lines.append(line)

    return '\n'.join(filtered_lines)

def clean_text(text: str) -> str:
    """
    清理 Claude Code 输出，移除 ANSI 转义序列和多余空白

    先清理 ANSI 代码，然后去除首尾空白，最后发送给 MCP
    """
    # return text # testing...

    if not text:
        return ""

    # 先清理 ANSI 转义序列
    cleaned = clean_ansi_codes(text)

    cleaned = filter_ui_elements(cleaned)

    # 去除首尾空白
    cleaned = cleaned.strip()

    return cleaned


def simulate_coding_output():
    """Simulate Claude Code output, can be replaced with real subprocess stdout listening"""
    samples = [
        "Compiling project...",
        "Running tests...",
        "✅ All tests passed!",
        "Deployment complete."
    ]
    for s in samples:
        yield s
        time.sleep(1)


class TextBuffer:
    """
    文本缓冲区，累积数据并记录时间戳，用于决定发送时机
    确保只在行边界处发送，避免在行中间切断
    """
    def __init__(self, min_window_seconds=1.0, pause_threshold=2.0):
        self.buffer = ""  # 累积的文本数据
        self.window_start_time = None  # 当前窗口开始时间
        self.last_data_time = None  # 最后一次数据到达时间
        self.min_window_seconds = min_window_seconds  # 最小累积时间：1秒
        self.pause_threshold = pause_threshold  # 停顿阈值：2秒

    def add_data(self, text: str, current_time: float):
        """添加新数据到缓冲区，记录时间戳"""
        self.buffer += text
        if self.window_start_time is None:
            self.window_start_time = current_time
        self.last_data_time = current_time

    def has_complete_lines(self) -> bool:
        """检查缓冲区是否有完整的行（以换行符结尾）"""
        return self.buffer and '\n' in self.buffer

    def should_flush(self, current_time: float) -> bool:
        """
        判断是否应该刷新缓冲区

        返回 True 的情况：
        1. 缓冲区有完整行，且累积时间 >= 最小时间窗口（1秒）
        2. 距离上次数据到达超过停顿阈值（2秒），且有完整行
        3. 距离上次数据到达超过停顿阈值（2秒），且缓冲区很大（即使没有完整行，也要发送）
        """
        if not self.buffer:
            return False

        has_complete = self.has_complete_lines()

        # 检查是否超过最小时间窗口（必须有完整行）
        if self.window_start_time and \
           (current_time - self.window_start_time) >= self.min_window_seconds:
            if has_complete:
                return True

        # 检查是否超过停顿阈值
        if self.last_data_time and \
           (current_time - self.last_data_time) >= self.pause_threshold:
            # 如果有完整行，或者缓冲区很大（超过一定大小），就发送
            if has_complete or len(self.buffer) > 4096:
                return True

        return False

    def flush(self) -> str:
        """
        刷新缓冲区，返回完整的行，保留不完整的行在缓冲区中

        返回空字符串表示没有完整的行可发送
        """
        if not self.buffer:
            return ""

        # 找到最后一个换行符的位置
        last_newline = self.buffer.rfind('\n')

        if last_newline == -1:
            # 没有换行符，不发送（除非缓冲区很大，在停顿阈值情况下）
            if len(self.buffer) > 4096:
                # 缓冲区很大但没有换行符，可能是单行很长，发送全部
                result = self.buffer
                self.buffer = ""
                self.window_start_time = None
                self.last_data_time = None
                return result
            return ""

        # 发送到最后一个换行符为止的完整行
        result = self.buffer[:last_newline + 1]  # 包含换行符
        self.buffer = self.buffer[last_newline + 1:]  # 保留不完整的行

        # 如果缓冲区清空了，重置时间戳
        if not self.buffer:
            self.window_start_time = None
            self.last_data_time = None
        else:
            # 如果还有剩余数据，更新窗口开始时间（从剩余数据开始计算）
            self.window_start_time = time.time()

        return result

    def has_data(self) -> bool:
        """检查缓冲区是否有数据"""
        return bool(self.buffer)

    def flush_all(self) -> str:
        """
        强制刷新所有缓冲区内容（用于程序结束时）
        即使没有完整行也发送
        """
        if not self.buffer:
            return ""

        result = self.buffer
        self.buffer = ""
        self.window_start_time = None
        self.last_data_time = None
        return result


if __name__ == "__main__":
    import pty
    import select
    import termios
    import tty
    import signal
    import argparse

    parser = argparse.ArgumentParser(
        description='MCP Bridge - Run command in PTY and forward output to MCP server',
        epilog='''
Examples:
  python bridge.py claude
  python bridge.py python -i
  python bridge.py bash
        '''
    )
    parser.add_argument('command', nargs=argparse.REMAINDER,
                       help='Command to run in PTY (e.g., claude, python -i, bash)')
    args = parser.parse_args()

    if not args.command:
        parser.error("command is required")

    logger.info("🧩 Starting MCP Bridge...")
    bridge = MCPBridge()
    time.sleep(0.5)

    # 创建一个伪终端对
    master_fd, slave_fd = pty.openpty()

    # 获取终端名称
    slave_name = os.ttyname(slave_fd)
    logger.info(f"📺 Created PTY: {slave_name}")

    # 保存当前终端设置
    old_settings = termios.tcgetattr(sys.stdin)

    # 从命令行参数获取要运行的命令
    cmd = args.command
    logger.info(f"🚀 Running command in PTY: {' '.join(cmd)}")

    cmd_proc = subprocess.Popen(
        cmd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        start_new_session=True
    )

    # 关闭 slave_fd（master 端保持打开）
    os.close(slave_fd)

    # 设置终端为原始模式（用于正确处理输入）
    try:
        tty.setraw(sys.stdin.fileno())

        def restore_terminal():
            """恢复终端设置"""
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

        # 注册信号处理，确保退出时恢复终端
        def signal_handler(sig, frame):
            restore_terminal()
            os.close(master_fd)
            if cmd_proc.poll() is None:
                cmd_proc.terminate()
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # 初始化文本缓冲区
        text_buffer = TextBuffer(min_window_seconds=1.0, pause_threshold=2.0)

        # 双向通信循环
        try:
            while True:
                current_time = time.time()

                # 检查是否应该刷新缓冲区（即使没有新数据）
                if text_buffer.should_flush(current_time):
                    buffered_text = text_buffer.flush()
                    if buffered_text:
                        clean = clean_text(buffered_text)
                        if clean:
                            bridge.send_chunk(clean)

                # 检查哪些文件描述符有数据可读
                ready, _, _ = select.select([master_fd, sys.stdin], [], [], 0.1)

                # 从命令的输出（master_fd）读取
                if master_fd in ready:
                    try:
                        data = os.read(master_fd, 1024)
                        if not data:
                            break

                        # 输出到终端
                        sys.stdout.buffer.write(data)
                        sys.stdout.buffer.flush()

                        # 添加到缓冲区（不立即处理）
                        try:
                            text = data.decode('utf-8', errors='replace')
                            current_time = time.time()
                            text_buffer.add_data(text, current_time)

                            # 检查是否应该刷新
                            if text_buffer.should_flush(current_time):
                                buffered_text = text_buffer.flush()
                                if buffered_text:
                                    clean = clean_text(buffered_text)
                                    if clean:
                                        bridge.send_chunk(clean)
                        except Exception as e:
                            logger.debug(f"Error processing text: {e}")
                    except OSError:
                        break

                # 从用户输入（stdin）读取，转发给命令
                if sys.stdin in ready:
                    try:
                        data = os.read(sys.stdin.fileno(), 1024)
                        if not data:
                            break
                        # 转发给命令
                        os.write(master_fd, data)
                    except OSError:
                        break

                # 检查进程是否结束
                if cmd_proc.poll() is not None:
                    # 读取剩余数据
                    while True:
                        ready, _, _ = select.select([master_fd], [], [], 0.1)
                        if not ready:
                            break
                        try:
                            data = os.read(master_fd, 1024)
                            if not data:
                                break
                            sys.stdout.buffer.write(data)
                            sys.stdout.buffer.flush()

                            # 添加到缓冲区
                            text = data.decode('utf-8', errors='replace')
                            current_time = time.time()
                            text_buffer.add_data(text, current_time)
                        except OSError:
                            break

                    # 处理剩余缓冲区
                    buffered_text = text_buffer.flush_all()
                    if buffered_text:
                        clean = clean_text(buffered_text)
                        if clean:
                            bridge.send_chunk(clean)
                    break

        except KeyboardInterrupt:
            logger.info("⚠️ Interrupted by user")
        finally:
            restore_terminal()

            # 处理最后剩余的缓冲区
            if text_buffer.has_data():
                buffered_text = text_buffer.flush_all()
                if buffered_text:
                    clean = clean_text(buffered_text)
                    if clean:
                        bridge.send_chunk(clean)

    finally:
        os.close(master_fd)
        if cmd_proc.poll() is None:
            cmd_proc.terminate()
        cmd_proc.wait()

        # 等待所有响应
        # logger.info("⏳ Waiting for MCP Server responses...")
        bridge.wait_for_responses(timeout=2.0)
        logger.info("✅ All responses received (or timeout)")
