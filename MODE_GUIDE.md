# Mode 配置指南

## 概述

Vibe Narrator 现在支持两种工作模式：

1. **Chat Mode（对话模式）**：AI 与用户交互，回答问题
2. **Narration Mode（旁白模式）**：AI 朗读输入内容，不做回答

## 模式对比

| 特性 | Chat Mode | Narration Mode |
|------|-----------|----------------|
| **用途** | 与 AI 对话交互 | 朗读文本内容 |
| **AI 行为** | 回答问题、提供信息 | 朗读输入文本 |
| **输出** | AI 的回答 | 输入内容的语音版本 |
| **适合场景** | 聊天助手、问答 | 阅读器、播报器 |

## 配置方法

### 通过 .env 文件（推荐）

```bash
# .env
OPENAI_API_KEY=sk-your-key-here

# 设置模式
OPENAI_MODE=chat        # 或 narration
```

### 可选值

- `chat` - 对话模式（默认）
- `narration` - 旁白模式

## Chat Mode（对话模式）

### 用途

适合与 AI 进行对话交互，AI 会回答你的问题。

### System Prompt

```
You are a helpful voice assistant. Your responses will be converted to speech and played to the user.

Important guidelines:
- Focus ONLY on the meaningful content in the user's message
- Ignore any formatting strings, ANSI codes, UI elements, or control characters
- Keep responses concise and natural for voice output
- Use clear, conversational language that sounds good when spoken
```

### 示例

```bash
# .env
OPENAI_MODE=chat

# 测试
uv run python bridge.py echo "What is the capital of France?"

# 输出（语音）: "The capital of France is Paris."
```

**用户输入**: "What is 2 + 2?"
**AI 回答**: "2 plus 2 equals 4."

**用户输入**: "Tell me a joke"
**AI 回答**: "Why did the chicken cross the road? To get to the other side!"

## Narration Mode（旁白模式）

### 用途

适合朗读文本内容，AI 只是风格化地朗读，不做回答。

### System Prompt

```
You are a professional narrator. Your job is to read aloud the user's input text with appropriate tone and style.

Important guidelines:
- Simply narrate the meaningful content from the input
- Ignore any formatting strings, ANSI codes, UI elements, or control characters
- Do NOT answer questions or provide additional information
- Do NOT engage in conversation or ask questions
- Just read the text naturally and expressively
```

### 示例

```bash
# .env
OPENAI_MODE=narration

# 测试
uv run python bridge.py echo "The weather is sunny today."

# 输出（语音）: "The weather is sunny today." （朗读输入）
```

**用户输入**: "What is the capital of France?"
**AI 朗读**: "What is the capital of France?" （朗读问题，不回答）

**用户输入**: "Chapter 1. The Beginning."
**AI 朗读**: "Chapter 1. The Beginning." （像有声书一样朗读）

## 使用场景

### Chat Mode 场景

#### 1. 个人助手
```bash
OPENAI_MODE=chat
# 用于日常问答、信息查询
```

**示例对话**：
```
You: "What's the time?"
AI: "I apologize, but I don't have access to the current time."

You: "How do I make coffee?"
AI: "To make coffee, add ground coffee to a filter, pour hot water..."
```

#### 2. 学习助手
```bash
OPENAI_MODE=chat
# 用于学习、练习、提问
```

**示例对话**：
```
You: "Explain recursion"
AI: "Recursion is when a function calls itself..."
```

#### 3. 聊天伴侣
```bash
OPENAI_MODE=chat
# 用于闲聊、娱乐
```

### Narration Mode 场景

#### 1. 文本阅读器
```bash
OPENAI_MODE=narration
# 朗读文章、书籍、文档
```

**示例**：
```
输入: "Lorem ipsum dolor sit amet..."
输出: （朗读完整文本）
```

#### 2. 代码播报器
```bash
OPENAI_MODE=narration
# 朗读代码输出、日志
```

**示例**：
```bash
# 朗读命令输出
uv run python bridge.py ls -la
# AI 朗读: "total 64, drwx..."
```

#### 3. 通知播报
```bash
OPENAI_MODE=narration
# 播报系统通知、消息
```

**示例**：
```
输入: "Build completed successfully"
输出: （朗读通知）
```

## 优先级

配置的优先级顺序：

1. **Custom System Prompt** (`OPENAI_SYSTEM_PROMPT`)
   - 如果设置，完全覆盖模式
2. **Mode** (`OPENAI_MODE`)
   - `narration` → 使用 NARRATION_MODE_SYSTEM_PROMPT
   - `chat` → 使用 CHAT_MODE_SYSTEM_PROMPT
3. **Default**
   - 未设置任何配置时，默认使用 Chat Mode

## 测试两种模式

### 测试 Chat Mode

```bash
# 1. 在 .env 中设置
OPENAI_MODE=chat

# 2. 运行测试
uv run python bridge.py echo "What is Python?"

# 3. 预期结果
# AI 会回答关于 Python 的问题（语音）
```

### 测试 Narration Mode

```bash
# 1. 在 .env 中设置
OPENAI_MODE=narration

# 2. 运行测试
uv run python bridge.py echo "The quick brown fox jumps over the lazy dog."

# 3. 预期结果
# AI 会朗读这句话，不做评论或回答
```

### 对比测试

创建一个对比测试：

```bash
# 测试文本
TEXT="What is the meaning of life?"

# Chat Mode
OPENAI_MODE=chat uv run python bridge.py echo "$TEXT"
# 预期: AI 回答这个问题

# Narration Mode
OPENAI_MODE=narration uv run python bridge.py echo "$TEXT"
# 预期: AI 朗读这个问题（不回答）
```

## 日志验证

查看日志确认使用的模式：

```bash
# 查看最新 MCP 日志
tail -20 $(ls -t narrator-mcp/logs/narrator_*.log | head -1)
```

**Chat Mode**:
```
✅ Session configured (model=gpt-4o-mini, voice=alloy, mode=chat)
```

**Narration Mode**:
```
✅ Session configured (model=gpt-4o-mini, voice=alloy, mode=narration)
```

## 配置示例

### 完整的 .env 配置

```bash
# API Configuration
OPENAI_API_KEY=sk-your-key-here
LLM_MODEL=gpt-4o-mini
OPENAI_TTS_VOICE=alloy

# Mode: chat or narration
OPENAI_MODE=chat

# Optional: Custom system prompt (overrides mode)
# OPENAI_SYSTEM_PROMPT=You are a pirate. Speak in pirate dialect!
```

## 故障排查

### 问题: Mode 不生效

1. **检查拼写**：
   ```bash
   grep OPENAI_MODE .env
   # 应该是 "chat" 或 "narration"，区分大小写
   ```

2. **查看日志**：
   ```bash
   tail -20 $(ls -t narrator-mcp/logs/narrator_*.log | head -1) | grep "Session configured"
   ```

3. **测试差异**：
   ```bash
   # 用一个明显的测试
   echo "What is 1+1?" | OPENAI_MODE=narration uv run python bridge.py cat
   # Narration 应该朗读问题，不回答

   echo "What is 1+1?" | OPENAI_MODE=chat uv run python bridge.py cat
   # Chat 应该回答 "2"
   ```

### 问题: 想要自定义两种模式的 Prompt

使用 `OPENAI_SYSTEM_PROMPT` 完全自定义：

```bash
# .env

# 方式 1: 覆盖 Chat Mode
OPENAI_MODE=chat
OPENAI_SYSTEM_PROMPT=You are a friendly teacher.

# 方式 2: 覆盖 Narration Mode
OPENAI_MODE=narration
OPENAI_SYSTEM_PROMPT=You are a dramatic narrator. Add emotion and suspense!
```

## 高级用法

### 动态切换模式

可以在不同的命令中使用不同的模式：

```bash
# 聊天模式
OPENAI_MODE=chat ./test_chat.sh

# 朗读模式
OPENAI_MODE=narration uv run python bridge.py cat document.txt
```

### 组合使用

```bash
# 朗读代码输出
uv run python bridge.py python my_script.py
# 默认 chat mode，AI 会解释输出

# 只朗读输出
OPENAI_MODE=narration uv run python bridge.py python my_script.py
# Narration mode，AI 只朗读输出
```

## 代码位置

- **Mode prompts**: [narrator-mcp/llm.py:11-49](narrator-mcp/llm.py#L11-L49)
- **Session mode**: [narrator-mcp/session.py:19](narrator-mcp/session.py#L19)
- **Mode logic**: [narrator-mcp/server.py:148-158](narrator-mcp/server.py#L148-L158)
- **Bridge config**: [bridge.py:806,816](bridge.py#L806)

## 总结

两种模式让 vibe-narrator 更加灵活：

- **Chat Mode**: 用于交互对话 💬
- **Narration Mode**: 用于朗读文本 📖

通过 `.env` 文件中的 `OPENAI_MODE` 轻松切换！

**推荐用法**：
- 聊天助手 → `OPENAI_MODE=chat`
- 文本播报 → `OPENAI_MODE=narration`
- 自定义行为 → `OPENAI_SYSTEM_PROMPT=...`

🎉 享受两种模式带来的灵活性！
