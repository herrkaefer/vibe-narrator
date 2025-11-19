# 聊天模式使用指南

## 概述

Vibe Narrator 现在支持交互式聊天模式！你可以在终端中输入消息，AI 会通过语音回复（不在终端显示文本）。

## 快速开始

### 方式 1: 使用测试脚本（推荐）

```bash
./test_chat.sh
```

### 方式 2: 直接运行

```bash
uv run python bridge.py python chat.py
```

## 工作原理

```
┌─────────────┐
│   用户      │  输入: "Hello!"
│   终端      │
└──────┬──────┘
       │ stdout
       ▼
┌─────────────┐
│  chat.py    │  转发用户输入到 stdout
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  bridge.py  │  捕获输出，发送到 MCP
└──────┬──────┘
       │ JSON-RPC
       ▼
┌─────────────┐
│  MCP Server │  LLM 生成回复 + TTS 转语音
└──────┬──────┘
       │ Audio Events
       ▼
┌─────────────┐
│ AudioPlayer │  播放 AI 语音回复
└─────────────┘
       │
       ▼
    🔊 扬声器
```

**关键设计**：
- ✅ 用户输入显示在终端
- ✅ AI 回复通过语音播放
- ✅ 不在终端显示 AI 文本回复
- ✅ 支持多轮连续对话

## 使用示例

### 启动聊天

```bash
$ ./test_chat.sh

🎤 Vibe Narrator Chat
==================================================

Type your messages and press Enter.
The AI will respond via audio (not shown in terminal).

Commands:
  /quit or /exit - Exit the chat
  /clear - Clear conversation history (not implemented yet)

==================================================

You: Hello! How are you?
Hello! How are you?

You: What's the weather like today?
What's the weather like today?

You: /quit
👋 Goodbye!
```

### 实际体验

1. **你输入**: "Hello! How are you?"
   - 终端显示: `You: Hello! How are you?`
   - 你听到: AI 用语音回答你的问题

2. **继续对话**: "Tell me a joke"
   - 终端显示: `You: Tell me a joke`
   - 你听到: AI 讲笑话（语音）

3. **退出**: `/quit`

## 特殊命令

| 命令 | 功能 |
|------|------|
| `/quit` 或 `/exit` | 退出聊天 |
| `/clear` | 清空对话历史（暂未实现） |
| `Ctrl+C` | 强制退出 |
| `Ctrl+D` | 优雅退出 |

## 与其他模式的对比

### Echo 模式 (单次)
```bash
uv run python bridge.py echo "Hello!"
```
- 单次输入
- 立即退出
- 适合测试

### 聊天模式 (多轮)
```bash
./test_chat.sh
```
- 连续对话
- 多轮交互
- 类似 ChatGPT

### Claude Code 集成
```bash
uv run python bridge.py claude
```
- 完整的 Claude Code 体验
- 包含 UI 格式控制
- 工具调用等高级功能

## 技术细节

### chat.py 设计

```python
# 核心逻辑很简单
while True:
    user_input = input("You: ")

    # 直接输出到 stdout
    print(user_input)
    sys.stdout.flush()

    # bridge 会捕获这个输出并处理
```

**为什么这样设计？**

1. **简单**：不需要复杂的通信协议
2. **通用**：任何能输出文本的程序都可以用
3. **解耦**：chat.py 不需要知道 bridge 的存在
4. **可靠**：使用标准的 stdin/stdout

### Bridge 的角色

Bridge 通过 PTY（伪终端）捕获 chat.py 的输出：

1. 捕获用户输入的文本
2. 清理 ANSI 码和 UI 元素
3. 发送到 MCP server
4. 接收音频事件
5. 播放语音

## 配置选项

在 `.env` 中可以配置：

```bash
# AI 模型
OPENAI_MODEL=gpt-4o-mini

# 语音选项
OPENAI_VOICE=alloy
# 可用: alloy, echo, fable, onyx, nova, shimmer
```

## 故障排查

### 问题: 听不到声音

1. 检查系统音量
2. 查看日志：
   ```bash
   tail -f $(ls -t logs/bridge_*.log | head -1)
   ```
3. 确认音频设备正常工作

### 问题: 输入后没有反应

可能原因：
- MCP server 连接失败
- API key 无效
- 网络问题

查看日志：
```bash
# Bridge 日志
tail -20 $(ls -t logs/bridge_*.log | head -1)

# MCP Server 日志
tail -20 $(ls -t narrator-mcp/logs/narrator_*.log | head -1)
```

### 问题: 退出时卡住

使用 `Ctrl+C` 强制退出。

## 日志位置

- **Bridge 日志**: `logs/bridge_YYYYMMDD_HHMMSS.log`
- **MCP 日志**: `narrator-mcp/logs/narrator_YYYYMMDD_HHMMSS.log`

## 高级用法

### 自定义提示词

未来可以支持系统提示词：

```bash
# 暂未实现
uv run python bridge.py python chat.py --system "You are a helpful assistant."
```

### 对话历史

当前每次输入都是独立的。未来可以支持：
- 保持对话上下文
- `/clear` 命令清空历史
- 历史记录保存/加载

## 性能

- **启动时间**: ~2-3 秒
- **首次回复**: ~2-3 秒（LLM + TTS）
- **后续回复**: ~2-3 秒
- **内存使用**: ~200MB

## 限制

当前版本的限制：

1. **无对话历史**：每次输入都是新对话
2. **无上下文**：AI 不记得之前的对话
3. **无历史清除**：`/clear` 命令未实现
4. **单用户**：不支持多用户同时使用

这些功能将在未来版本中实现。

## 示例场景

### 场景 1: 语音助手

```bash
You: Set a timer for 5 minutes
# AI 语音确认

You: What's 25 times 4?
# AI 语音回答: "100"

You: Tell me a fun fact
# AI 语音讲述有趣的事实
```

### 场景 2: 语言学习

```bash
You: How do you say "hello" in Spanish?
# AI 语音回答并教你发音

You: Can you repeat that slower?
# AI 慢速重复
```

### 场景 3: 故事讲述

```bash
You: Tell me a short story about a robot
# AI 用语音讲故事，非常生动！
```

## 相关文档

- [SETUP.md](SETUP.md) - 基本设置
- [AUDIO_SETUP.md](AUDIO_SETUP.md) - 音频配置
- [AUDIO_FIX.md](AUDIO_FIX.md) - 音频修复说明

## 反馈

使用中遇到问题？请查看日志并提供：
1. 操作系统版本
2. 错误日志
3. 重现步骤

享受与 AI 的语音对话！🎉
