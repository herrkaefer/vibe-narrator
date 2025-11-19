# Vibe Narrator Setup Guide

## 快速开始

### 1. 配置环境

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件,添加你的 OpenAI API key
# OPENAI_API_KEY=sk-your-actual-api-key-here
```

### 2. 安装依赖

```bash
uv sync
```

### 3. 测试

```bash
# 方式 1: 使用便捷测试脚本
./test_echo.sh

# 方式 2: 直接运行
uv run python bridge.py echo "Hello from vibe-narrator!"

# 方式 3: 与 Claude Code 集成
uv run python bridge.py claude
```

## 工作原理

### 架构

```
┌─────────────────┐
│  Command (e.g.  │
│  Claude Code)   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Bridge (PTY)   │  捕获输出,清理 ANSI 码
│  bridge.py      │
└────────┬────────┘
         │ JSON-RPC
         ▼
┌─────────────────┐
│  Narrator MCP   │  LLM + TTS 生成语音
│  server.py      │
└────────┬────────┘
         │
         ▼
  Audio Events (hex-encoded MP3)
```

### 流程

1. **Bridge** 启动命令并通过伪终端(PTY)捕获输出
2. **文本处理**:
   - 移除 ANSI 转义序列
   - 过滤 UI 元素
   - 批量发送文本块
3. **Narrator MCP Server**:
   - 接收文本
   - 调用 OpenAI LLM 处理
   - 调用 OpenAI TTS 生成语音
   - 发送音频事件回 bridge
4. **等待完成**: Bridge 等待所有音频生成完成后再退出(最多 30 秒)

## 配置选项

在 `.env` 文件中可以配置:

```bash
# 必需
OPENAI_API_KEY=sk-your-key-here

# 可选 (默认值如下)
OPENAI_MODEL=gpt-4o-mini
OPENAI_VOICE=alloy

# 可用的语音选项:
# alloy, echo, fable, onyx, nova, shimmer
```

## 测试脚本

| 脚本 | 用途 |
|------|------|
| `./diagnose.sh` | 诊断环境配置 |
| `./test_mcp_only.sh` | 测试 MCP server |
| `./test_echo.sh` | 完整测试(推荐) |
| `./test_simple.sh` | 简单测试 |

## 日志位置

- **Bridge 日志**: `logs/bridge_YYYYMMDD_HHMMSS.log`
- **Narrator 日志**: `narrator-mcp/logs/narrator_YYYYMMDD_HHMMSS.log`

## 故障排查

### 问题: "OPENAI_API_KEY not found"

```bash
# 确保 .env 文件存在
ls -la .env

# 检查内容
cat .env
```

### 问题: "ModuleNotFoundError: No module named 'openai'"

```bash
# 重新安装依赖
uv sync
```

### 问题: "Config timeout" 或 "Broken pipe"

```bash
# 检查 MCP server 是否能独立运行
cd narrator-mcp
uv run python server.py
# 发送测试消息 (Ctrl+C 退出)

# 查看最新日志
tail -50 logs/bridge_*.log | tail -1
```

### 问题: 程序立即退出,音频未生成

✅ **已修复!** Bridge 现在会等待最多 30 秒让所有音频生成完成。

查看日志确认:
```bash
tail -20 $(ls -t logs/bridge_*.log | head -1) | grep "⏳\\|✅\\|⚠️"
```

应该看到:
```
⏳ Waiting for narration to complete...
✅ All narrations completed
✅ Bridge shutdown complete
```

## 高级用法

### 自定义命令

```bash
# Python REPL
uv run python bridge.py python -i

# Bash shell
uv run python bridge.py bash

# 任何交互式命令
uv run python bridge.py <your-command>
```

### 调试模式

编辑 `bridge.py` 第 128 行:
```python
level=logging.DEBUG,  # 改为 DEBUG 查看详细日志
```

## 性能优化

### 文本缓冲

Bridge 使用智能缓冲:
- **最小时间窗口**: 1 秒
- **暂停阈值**: 2 秒
- 只在行边界发送,避免切断句子

### 等待时间

默认等待 30 秒让音频生成完成。如需调整,编辑 `bridge.py` 第 918 行:
```python
bridge.wait_for_responses(timeout=30.0)  # 调整秒数
```

## 贡献

欢迎提交 issue 和 pull request!
