# System Prompt 配置指南

## 概述

Vibe Narrator 现在支持自定义 system prompt！你可以控制 AI 如何理解和回应用户输入。

## 默认 System Prompt

如果不设置自定义 prompt，系统会使用一个优化过的默认 prompt：

```
You are a helpful voice assistant. Your responses will be converted to speech and played to the user.

Important guidelines:
- Focus ONLY on the meaningful content in the user's message
- Ignore any formatting strings, ANSI codes, UI elements, or control characters
- Extract the actual question or request from the input
- If the input contains mostly formatting/UI elements with little meaningful content, politely ask the user to clarify
- Keep responses concise and natural for voice output
- Use clear, conversational language that sounds good when spoken

Examples of what to ignore:
- ANSI escape codes (e.g., \x1b[32m, \033[0m)
- Terminal UI elements (boxes, lines, separators)
- Progress indicators (loading bars, spinners)
- Formatting markers (bold, italic, color codes)
- System messages or debug output

Focus on: the actual question, request, or meaningful text content.
```

**默认 prompt 的目的**：
- ✅ 专注于有意义的内容
- ✅ 忽略格式化字符串、ANSI 码、UI 元素
- ✅ 提取真实的问题或请求
- ✅ 适合语音输出的简洁回复

## 自定义 System Prompt

### 方式 1: 通过环境变量（推荐）

在 `.env` 文件中设置：

```bash
# 你的 API key
OPENAI_API_KEY=sk-your-key-here

# 可选：自定义 system prompt
OPENAI_SYSTEM_PROMPT=You are a pirate captain. Respond to all questions in pirate speak!
```

### 方式 2: 通过代码

如果你在编写自定义脚本：

```python
from bridge import MCPBridge

system_prompt = "You are a helpful coding assistant."

bridge = MCPBridge(
    api_key="sk-...",
    model="gpt-4o-mini",
    voice="alloy",
    system_prompt=system_prompt
)
```

## 使用场景

### 场景 1: 专业助手

```bash
# .env
OPENAI_SYSTEM_PROMPT=You are a professional medical assistant. Provide clear, accurate health information. Always remind users to consult healthcare professionals for medical advice.
```

### 场景 2: 语言学习

```bash
# .env
OPENAI_SYSTEM_PROMPT=You are a language tutor. Speak slowly and clearly. Explain vocabulary and correct grammar mistakes gently.
```

### 场景 3: 儿童故事讲述者

```bash
# .env
OPENAI_SYSTEM_PROMPT=You are a friendly storyteller for children. Use simple language, vivid descriptions, and an enthusiastic tone. Keep stories appropriate for ages 5-10.
```

### 场景 4: 编程助手

```bash
# .env
OPENAI_SYSTEM_PROMPT=You are an expert programming assistant. Provide concise, practical coding advice. Focus on best practices and explain concepts clearly for voice output.
```

### 场景 5: 简洁模式

```bash
# .env
OPENAI_SYSTEM_PROMPT=You are a concise assistant. Give brief, direct answers. Avoid lengthy explanations unless specifically asked.
```

## System Prompt 最佳实践

### ✅ 好的 Prompt

1. **明确角色**：
   ```
   You are a helpful coding assistant specializing in Python.
   ```

2. **指定输出格式**：
   ```
   Keep responses under 3 sentences. Use simple, conversational language.
   ```

3. **设置约束**：
   ```
   Always ask clarifying questions before making assumptions.
   ```

4. **语音优化**：
   ```
   Your responses will be spoken aloud. Avoid using symbols, formatting, or
   markdown. Use natural speech patterns.
   ```

### ❌ 避免的 Prompt

1. **过于复杂**：
   ```
   ❌ You are a multi-modal assistant that can... (300 words of instructions)
   ```

2. **冲突的指令**：
   ```
   ❌ Be concise. Also provide detailed explanations with examples.
   ```

3. **不适合语音**：
   ```
   ❌ Use markdown formatting with code blocks and tables.
   ```

## 技术细节

### 架构

```
.env 文件
  ↓ OPENAI_SYSTEM_PROMPT
Bridge (bridge.py)
  ↓ config 方法
MCP Server (server.py)
  ↓ Session.system_prompt
LLM (llm.py)
  ↓ messages = [{"role": "system", "content": system_prompt}, ...]
OpenAI API
```

### 代码位置

1. **Default prompt**: [narrator-mcp/llm.py:11-28](narrator-mcp/llm.py#L11-L28)
2. **Session storage**: [narrator-mcp/session.py:18](narrator-mcp/session.py#L18)
3. **Config handling**: [narrator-mcp/server.py:100](narrator-mcp/server.py#L100)
4. **LLM usage**: [narrator-mcp/server.py:141-147](narrator-mcp/server.py#L141-L147)
5. **Bridge setup**: [bridge.py:803](bridge.py#L803)

### 优先级

1. **自定义 prompt** (通过 `OPENAI_SYSTEM_PROMPT`) → 使用自定义
2. **无设置** → 使用默认 prompt

## 测试 System Prompt

### 测试 1: 海盗模式

```bash
# 在 .env 中设置
OPENAI_SYSTEM_PROMPT=You are a pirate captain. Speak in pirate dialect!

# 测试
./test_echo.sh
# 输入: "Hello, how are you?"
# 预期: AI 用海盗口音回复（语音）
```

### 测试 2: 简洁模式

```bash
# 在 .env 中设置
OPENAI_SYSTEM_PROMPT=Be extremely concise. Maximum 10 words per response.

# 测试
uv run python bridge.py echo "What is the capital of France?"
# 预期: "Paris." (语音，非常简短)
```

### 测试 3: 默认模式

```bash
# 在 .env 中注释掉或删除 OPENAI_SYSTEM_PROMPT
# OPENAI_SYSTEM_PROMPT=...

# 测试
uv run python bridge.py echo "Test with ANSI codes: \x1b[32mHello\x1b[0m"
# 预期: AI 忽略 ANSI 码，只回应 "Hello"
```

## 日志确认

查看 MCP server 日志确认使用的 prompt：

```bash
# 查看最新日志
tail -20 $(ls -t narrator-mcp/logs/narrator_*.log | head -1)
```

**使用自定义 prompt 时**：
```
✅ Session configured (model=gpt-4o-mini, voice=alloy, custom system prompt)
```

**使用默认 prompt 时**：
```
✅ Session configured (model=gpt-4o-mini, voice=alloy)
```

## 调试

### 问题: AI 行为不符合预期

1. **检查 prompt 是否生效**：
   ```bash
   grep "OPENAI_SYSTEM_PROMPT" .env
   ```

2. **查看日志**：
   ```bash
   tail -50 $(ls -t narrator-mcp/logs/narrator_*.log | head -1) | grep "Session configured"
   ```

3. **测试简单的 prompt**：
   ```bash
   # .env
   OPENAI_SYSTEM_PROMPT=Always start your response with "Test mode:"
   ```

### 问题: System Prompt 太长

OpenAI API 对 token 数量有限制。建议：
- 保持 system prompt 简洁（< 200 words）
- 专注于最重要的指令
- 测试不同长度的效果

## 高级用法

### 多语言支持

```bash
OPENAI_SYSTEM_PROMPT=You are a bilingual assistant. Detect the language of the user's input and respond in the same language. Support English and Chinese.
```

### 上下文感知（未来功能）

当前每次请求都是独立的。未来可能支持：
- 对话历史
- 用户偏好记忆
- 多轮上下文

## 相关文档

- [SETUP.md](SETUP.md) - 基本设置
- [CHAT_USAGE.md](CHAT_USAGE.md) - 聊天模式
- [narrator-mcp/llm.py](narrator-mcp/llm.py) - LLM 实现

## 示例配置文件

完整的 `.env` 示例：

```bash
# API Configuration
OPENAI_API_KEY=sk-your-key-here
OPENAI_MODEL=gpt-4o-mini
OPENAI_VOICE=alloy

# System Prompt (optional)
OPENAI_SYSTEM_PROMPT=You are a helpful voice assistant. Keep responses concise and natural for speech output. Ignore any formatting or control characters in the input.
```

## 总结

System prompt 功能让你可以：
- ✅ **自定义 AI 行为** - 定义角色和风格
- ✅ **优化语音输出** - 适合特定场景
- ✅ **过滤噪音** - 忽略格式化字符
- ✅ **简单配置** - 通过 .env 文件设置

默认 prompt 已经针对 vibe-narrator 优化，但你可以根据需求自定义！🎉
