# Mode 功能实现总结

## ✅ 已完成的实现

实现了两种工作模式：**Chat Mode** 和 **Narration Mode**

## 模式说明

### 1. Chat Mode（对话模式）- 默认

**用途**: AI 与用户交互，回答问题

**行为**:
- 用户提问 → AI 回答
- 类似 ChatGPT 的对话体验
- 提供信息、解释、建议

**System Prompt** ([llm.py:12-26](narrator-mcp/llm.py#L12-L26)):
```python
CHAT_MODE_SYSTEM_PROMPT = """You are a helpful voice assistant...
- Focus ONLY on the meaningful content
- Ignore formatting strings, ANSI codes, UI elements
- Keep responses concise and natural for voice output
"""
```

**示例**:
```
输入: "What is Python?"
输出: "Python is a programming language..."
```

### 2. Narration Mode（旁白模式）

**用途**: AI 朗读输入内容，不做回答

**行为**:
- 输入文本 → AI 朗读
- 风格化的语音播报
- 不回答问题，不提供额外信息

**System Prompt** ([llm.py:29-46](narrator-mcp/llm.py#L29-L46)):
```python
NARRATION_MODE_SYSTEM_PROMPT = """You are a professional narrator...
- Simply narrate the meaningful content from the input
- Do NOT answer questions or provide additional information
- Do NOT engage in conversation
- Just read the text naturally and expressively
"""
```

**示例**:
```
输入: "What is Python?"
输出: "What is Python?" （朗读问题，不回答）
```

## 代码修改

### 1. LLM Prompts ([narrator-mcp/llm.py](narrator-mcp/llm.py))

```python
# 新增两个 system prompts
CHAT_MODE_SYSTEM_PROMPT = """..."""
NARRATION_MODE_SYSTEM_PROMPT = """..."""

# 导出
__all__ = ["DEFAULT_MODEL", "stream_llm",
           "CHAT_MODE_SYSTEM_PROMPT", "NARRATION_MODE_SYSTEM_PROMPT"]
```

### 2. Session ([narrator-mcp/session.py:19](narrator-mcp/session.py#L19))

```python
DEFAULT_MODE = "chat"

class Session:
    def __init__(self):
        self.mode: str = DEFAULT_MODE  # "chat" or "narration"
        self.system_prompt: Optional[str] = None  # Custom (overrides mode)
```

### 3. Server Config ([narrator-mcp/server.py:100](narrator-mcp/server.py#L100))

```python
# 接收 mode 配置
session.mode = params.get("mode", session.mode)

# 日志
config_info = f"model={session.model}, voice={session.voice}, mode={session.mode}"
logging.info(f"✅ Session configured ({config_info})")
```

### 4. Mode Logic ([narrator-mcp/server.py:148-158](narrator-mcp/server.py#L148-L158))

```python
# 优先级: custom system_prompt > mode-based > default
if session.system_prompt is not None:
    stream_params["system_prompt"] = session.system_prompt
elif session.mode == "narration":
    stream_params["system_prompt"] = NARRATION_MODE_SYSTEM_PROMPT
elif session.mode == "chat":
    stream_params["system_prompt"] = CHAT_MODE_SYSTEM_PROMPT
```

### 5. Bridge ([bridge.py](bridge.py))

**__init__** (L146):
```python
def __init__(self, ..., mode=None, ...):
    self.mode = mode  # "chat" or "narration"
```

**_send_config** (L250-251):
```python
if self.mode:
    config_params["mode"] = self.mode
```

**main** (L806):
```python
mode = os.getenv("OPENAI_MODE")
bridge = MCPBridge(..., mode=mode, ...)
```

### 6. Environment ([.env.example](..env.example#L14-L18))

```bash
# Optional: Mode of operation (default: chat)
# Options:
#   - chat: AI responds to questions and interacts with user
#   - narration: AI narrates the input text with style (no interaction)
OPENAI_MODE=chat
```

## 配置优先级

```
1. OPENAI_SYSTEM_PROMPT (自定义 prompt)
   ↓ 如果未设置
2. OPENAI_MODE + 对应的 prompt
   - chat → CHAT_MODE_SYSTEM_PROMPT
   - narration → NARRATION_MODE_SYSTEM_PROMPT
   ↓ 如果未设置
3. Default (chat mode)
```

## 使用方法

### 通过 .env 文件

```bash
# Chat Mode (默认)
OPENAI_MODE=chat

# Narration Mode
OPENAI_MODE=narration

# 自定义（覆盖 mode）
OPENAI_SYSTEM_PROMPT=You are a pirate.
```

### 通过环境变量

```bash
# 临时使用 narration mode
OPENAI_MODE=narration uv run python bridge.py echo "Hello World"
```

## 测试

### Chat Mode 测试

```bash
# .env
OPENAI_MODE=chat

# 运行
uv run python bridge.py echo "What is 2+2?"

# 预期: AI 回答 "4" 或 "2 plus 2 equals 4"
```

### Narration Mode 测试

```bash
# .env
OPENAI_MODE=narration

# 运行
uv run python bridge.py echo "What is 2+2?"

# 预期: AI 朗读 "What is 2 plus 2?" （不回答）
```

### 验证日志

```bash
tail -20 $(ls -t narrator-mcp/logs/narrator_*.log | head -1)

# Chat mode:
# ✅ Session configured (model=gpt-4o-mini, voice=alloy, mode=chat)

# Narration mode:
# ✅ Session configured (model=gpt-4o-mini, voice=alloy, mode=narration)
```

## 实际应用

### Chat Mode 场景

```bash
# 聊天助手
./test_chat.sh
# 用户可以提问，AI 回答

# 语音问答
uv run python bridge.py echo "How do I learn Python?"
# AI 提供学习建议
```

### Narration Mode 场景

```bash
# 朗读文档
OPENAI_MODE=narration uv run python bridge.py cat README.md
# AI 朗读文档内容

# 播报命令输出
OPENAI_MODE=narration uv run python bridge.py ls -la
# AI 朗读目录列表

# 有声书
OPENAI_MODE=narration uv run python bridge.py cat story.txt
# AI 朗读故事（像有声书）
```

## 文件清单

### 新增文件
1. `MODE_GUIDE.md` - 用户使用指南
2. `MODE_IMPLEMENTATION.md` - 本文档（技术实现）

### 修改文件

| 文件 | 修改内容 | 行号 |
|------|---------|------|
| `narrator-mcp/llm.py` | 添加两种模式的 prompts | 11-49 |
| `narrator-mcp/llm.py` | 导出新 prompts | 82 |
| `narrator-mcp/session.py` | 添加 `mode` 字段 | 9, 19 |
| `narrator-mcp/session.py` | 导出 `DEFAULT_MODE` | 23 |
| `narrator-mcp/server.py` | 导入 mode prompts | 17 |
| `narrator-mcp/server.py` | Config 接收 `mode` | 100 |
| `narrator-mcp/server.py` | 日志显示 mode | 104-107 |
| `narrator-mcp/server.py` | Mode 选择逻辑 | 148-158 |
| `bridge.py` | `__init__` 接受 `mode` | 146 |
| `bridge.py` | `_send_config` 发送 `mode` | 250-251 |
| `bridge.py` | 日志显示 mode | 262 |
| `bridge.py` | 从环境读取 `mode` | 806 |
| `bridge.py` | 传递 `mode` 到 MCPBridge | 816 |
| `.env.example` | 添加 `OPENAI_MODE` 配置 | 14-18 |

## 架构流程

```
.env 文件
  ↓
OPENAI_MODE=chat/narration
  ↓
bridge.py (L806)
  ↓
MCPBridge(mode=...)
  ↓
_send_config(mode) → MCP Server
  ↓
server.py handle_config (L100)
  ↓
session.mode = "chat"/"narration"
  ↓
server.py run_llm (L148-158)
  ↓
if mode == "narration":
    system_prompt = NARRATION_MODE_SYSTEM_PROMPT
elif mode == "chat":
    system_prompt = CHAT_MODE_SYSTEM_PROMPT
  ↓
stream_llm(system_prompt=...)
  ↓
OpenAI API (不同的 system prompt)
```

## 设计理念

1. **简单配置**: 通过一个环境变量 `OPENAI_MODE` 切换
2. **清晰分离**: 两种模式有明确不同的行为
3. **优先级明确**: custom prompt > mode > default
4. **向后兼容**: 不设置 mode = chat mode（默认行为）
5. **灵活扩展**: 未来可以添加更多模式

## 对比表

| 方面 | Chat Mode | Narration Mode |
|------|-----------|----------------|
| **Prompt** | CHAT_MODE_SYSTEM_PROMPT | NARRATION_MODE_SYSTEM_PROMPT |
| **行为** | 回答问题 | 朗读输入 |
| **输出** | AI 生成的回答 | 输入的语音版本 |
| **典型输入** | "What is X?" | "Chapter 1..." |
| **典型输出** | "X is..." | "Chapter 1..." |
| **适用场景** | 助手、问答 | 阅读、播报 |

## 总结

✅ **双模式支持已完全实现**

- **Chat Mode**: 对话交互 💬
- **Narration Mode**: 语音播报 📖
- **简单配置**: 通过 `.env` 中的 `OPENAI_MODE`
- **完整文档**: MODE_GUIDE.md
- **向后兼容**: 默认 chat mode
- **灵活扩展**: 支持自定义 prompt 覆盖

现在 vibe-narrator 可以根据不同场景使用不同的模式！🎉
