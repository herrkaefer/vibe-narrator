# 模式快速参考

## 两种模式

| Mode | 说明 | 使用场景 |
|------|------|----------|
| **chat** | AI 回答问题 | 聊天助手、问答系统 |
| **narration** | AI 朗读文本 | 文本播报、有声书 |

## 快速配置

### .env 文件

```bash
# Chat Mode (默认)
OPENAI_MODE=chat

# Narration Mode
OPENAI_MODE=narration
```

## 对比示例

### 相同输入，不同输出

**输入**: "What is Python?"

| Mode | 输出（语音） |
|------|-------------|
| **chat** | "Python is a programming language..." |
| **narration** | "What is Python?" （朗读问题） |

**输入**: "Chapter 1. The Beginning."

| Mode | 输出（语音） |
|------|-------------|
| **chat** | "It sounds like you're starting a story..." |
| **narration** | "Chapter 1. The Beginning." （朗读文本） |

## 使用示例

### Chat Mode

```bash
# 在 .env 中设置
OPENAI_MODE=chat

# 使用
./test_chat.sh
uv run python bridge.py echo "Hello!"
```

### Narration Mode

```bash
# 在 .env 中设置
OPENAI_MODE=narration

# 朗读文档
uv run python bridge.py cat document.txt

# 播报命令输出
uv run python bridge.py ls -la
```

## 配置优先级

```
1. OPENAI_SYSTEM_PROMPT （最高优先级）
   ↓
2. OPENAI_MODE (chat/narration)
   ↓
3. Default (chat)
```

## 完整配置示例

```bash
# .env

# 必需
OPENAI_API_KEY=sk-your-key-here

# 可选
LLM_MODEL=gpt-4o-mini
OPENAI_TTS_VOICE=alloy
OPENAI_MODE=chat

# 高级：自定义 prompt（覆盖 mode）
# OPENAI_SYSTEM_PROMPT=You are a friendly teacher.
```

## 快速测试

```bash
# 测试 Chat Mode
OPENAI_MODE=chat uv run python bridge.py echo "What is 1+1?"
# 预期: "2" 或 "1 plus 1 equals 2"

# 测试 Narration Mode
OPENAI_MODE=narration uv run python bridge.py echo "What is 1+1?"
# 预期: "What is 1 plus 1?" （朗读问题）
```

## 文档链接

- **详细指南**: [MODE_GUIDE.md](MODE_GUIDE.md)
- **技术实现**: [MODE_IMPLEMENTATION.md](MODE_IMPLEMENTATION.md)
- **System Prompt**: [SYSTEM_PROMPT.md](SYSTEM_PROMPT.md)
