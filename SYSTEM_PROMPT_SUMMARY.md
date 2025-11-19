# System Prompt 功能总结

## ✅ 已完成的实现

### 1. 默认 System Prompt

在 [narrator-mcp/llm.py:11-28](narrator-mcp/llm.py#L11-L28) 添加了一个优化的默认 system prompt：

**核心功能**：
- ✅ 专注于有意义的内容
- ✅ 忽略 ANSI 转义码、格式化字符串、UI 元素
- ✅ 提取真实的问题或请求
- ✅ 简洁、自然的语音输出风格

**示例**：
```
输入: "\x1b[32mHello\x1b[0m ──── What is 2+2?"
AI 行为: 忽略 ANSI 码和分隔线，只回答 "2+2 equals 4"
```

### 2. 自定义 System Prompt 支持

#### Session 层 ([narrator-mcp/session.py:18](narrator-mcp/session.py#L18))
```python
class Session:
    def __init__(self):
        self.system_prompt: Optional[str] = None  # None = 使用默认
```

#### Config 处理 ([narrator-mcp/server.py:100](narrator-mcp/server.py#L100))
```python
session.system_prompt = params.get("system_prompt", session.system_prompt)
```

#### LLM 调用 ([narrator-mcp/server.py:141-147](narrator-mcp/server.py#L141-L147))
```python
stream_params = {
    "prompt": prompt,
    "api_key": session.api_key,
    "model": session.model
}
if session.system_prompt is not None:
    stream_params["system_prompt"] = session.system_prompt

async for token in stream_llm(**stream_params):
    # ...
```

#### Bridge 集成 ([bridge.py:803,812](bridge.py#L803))
```python
system_prompt = os.getenv("OPENAI_SYSTEM_PROMPT")
bridge = MCPBridge(api_key=api_key, model=model, voice=voice, system_prompt=system_prompt)
```

### 3. 环境变量配置

创建了 [.env.example](.env.example) 包含：

```bash
# Optional: Custom system prompt
# OPENAI_SYSTEM_PROMPT=You are a helpful assistant.
```

### 4. 文档

- **[SYSTEM_PROMPT.md](SYSTEM_PROMPT.md)** - 完整使用指南
  - 默认 prompt 说明
  - 自定义方法
  - 使用场景示例
  - 最佳实践
  - 故障排查

## 架构流程

```
.env 文件
  ↓
  OPENAI_SYSTEM_PROMPT (可选)
  ↓
bridge.py (L803)
  ↓
  os.getenv("OPENAI_SYSTEM_PROMPT")
  ↓
MCPBridge.__init__(system_prompt=...)
  ↓
config 方法 → MCP Server
  ↓
server.py handle_config (L100)
  ↓
session.system_prompt = params.get("system_prompt")
  ↓
server.py run_llm (L146-147)
  ↓
stream_llm(system_prompt=session.system_prompt)
  ↓
llm.py (L41-44)
  ↓
messages = [
    {"role": "system", "content": system_prompt or DEFAULT_SYSTEM_PROMPT},
    {"role": "user", "content": prompt}
]
  ↓
OpenAI API
```

## 使用示例

### 示例 1: 使用默认 Prompt

```bash
# .env 中不设置 OPENAI_SYSTEM_PROMPT

# 运行
uv run python bridge.py echo "Test: \x1b[32mHello\x1b[0m"

# 行为: AI 忽略 ANSI 码，只回应 "Hello"
```

### 示例 2: 自定义 Prompt

```bash
# .env
OPENAI_SYSTEM_PROMPT=You are a pirate. Speak in pirate dialect!

# 运行
uv run python bridge.py echo "Hello!"

# 行为: AI 用海盗口音回复（语音）
```

### 示例 3: 简洁模式

```bash
# .env
OPENAI_SYSTEM_PROMPT=Be extremely concise. Maximum 10 words per response.

# 运行
uv run python bridge.py echo "What is Python?"

# 行为: AI 给出非常简短的回答
```

## 验证方法

### 1. 检查日志

**使用自定义 prompt**：
```bash
tail -20 $(ls -t narrator-mcp/logs/narrator_*.log | head -1)
# 应该看到:
# ✅ Session configured (model=gpt-4o-mini, voice=alloy, custom system prompt)
```

**使用默认 prompt**：
```bash
# 应该看到:
# ✅ Session configured (model=gpt-4o-mini, voice=alloy)
```

### 2. 测试行为

```bash
# 测试格式化字符过滤
uv run python bridge.py echo "Ignore this: ████ Answer: What is 2+2?"

# 预期: AI 只回答数学问题，忽略进度条
```

## 代码修改总结

### 新增文件
1. `.env.example` - 环境变量模板
2. `SYSTEM_PROMPT.md` - 使用文档
3. `SYSTEM_PROMPT_SUMMARY.md` - 本文档

### 修改文件

| 文件 | 修改内容 | 行号 |
|------|---------|------|
| `narrator-mcp/llm.py` | 添加 `DEFAULT_SYSTEM_PROMPT` | 11-28 |
| `narrator-mcp/llm.py` | `stream_llm()` 接受 `system_prompt` 参数 | 31-50 |
| `narrator-mcp/session.py` | 添加 `system_prompt` 字段 | 18 |
| `narrator-mcp/server.py` | Config 处理 `system_prompt` | 100 |
| `narrator-mcp/server.py` | 传递 `system_prompt` 到 LLM | 141-147 |
| `bridge.py` | `MCPBridge` 接受 `system_prompt` | 146 |
| `bridge.py` | 发送 `system_prompt` 到 MCP | 249 |
| `bridge.py` | 从环境变量读取 `system_prompt` | 803 |

## 功能特性

✅ **默认行为优化**：
- 自动过滤格式化字符
- 专注有意义的内容
- 语音输出友好

✅ **完全可定制**：
- 通过 `.env` 文件配置
- 支持任意自定义 prompt
- 保留默认行为作为后备

✅ **向后兼容**：
- 不设置 = 使用默认 prompt
- 现有配置无需修改
- 渐进式增强

✅ **日志透明**：
- 明确显示使用哪个 prompt
- 便于调试和验证

## 测试用例

### 用例 1: 格式化字符过滤
```bash
输入: "Test: \x1b[32mGreen text\x1b[0m"
预期: AI 忽略 ANSI 码，只回应 "Green text"
```

### 用例 2: UI 元素过滤
```bash
输入: "Question: ────────── What is AI? ──────────"
预期: AI 只回答 "What is AI?"，忽略分隔线
```

### 用例 3: 自定义角色
```bash
OPENAI_SYSTEM_PROMPT=You are a teacher.
输入: "Explain variables"
预期: AI 用教学风格解释
```

## 未来增强

可能的改进方向：
- 📝 **对话历史**: 保留上下文
- 🎯 **场景切换**: 快速切换不同 prompt
- 💾 **Prompt 模板库**: 预设常用 prompt
- 🔧 **运行时修改**: 无需重启即可更改

## 总结

System prompt 功能已完全实现：
- ✅ 默认 prompt 优化了格式化字符过滤
- ✅ 支持通过 `.env` 自定义
- ✅ 完整的日志和文档
- ✅ 向后兼容
- ✅ 测试验证

现在 vibe-narrator 可以智能地忽略格式化字符串，专注于有意义的内容！🎉
