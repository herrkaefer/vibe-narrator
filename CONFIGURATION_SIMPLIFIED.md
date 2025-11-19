# 配置简化总结

## 变更内容

### 1. 移除 `OPENAI_SYSTEM_PROMPT`

**之前**:
```bash
# .env
OPENAI_MODE=chat
OPENAI_SYSTEM_PROMPT=You are a helpful assistant.  # 可选，覆盖 mode
```

**现在**:
```bash
# .env
MODE=chat  # 只需要设置 mode
```

**原因**: 简化配置，mode 已经足够满足需求

### 2. 重命名 `OPENAI_MODE` → `MODE`

**之前**: `OPENAI_MODE=chat`
**现在**: `MODE=chat`

**原因**: 更简洁，更直观

## 当前配置

### .env 文件

```bash
# 必需
OPENAI_API_KEY=sk-your-key-here

# 可选
OPENAI_MODEL=gpt-4o-mini
OPENAI_VOICE=alloy
MODE=chat  # 或 narration
```

## 两种模式

| Mode | 说明 |
|------|------|
| **chat** | AI 回答问题（默认） |
| **narration** | AI 朗读文本 |

## 示例

### Chat Mode (默认)

```bash
# .env
MODE=chat

# 或者不设置（默认就是 chat）
# MODE=

# 测试
uv run python bridge.py echo "What is Python?"
# AI 回答: "Python is a programming language..."
```

### Narration Mode

```bash
# .env
MODE=narration

# 测试
uv run python bridge.py echo "Chapter 1. The Beginning."
# AI 朗读: "Chapter 1. The Beginning."
```

## 代码修改

### 修改的文件

1. **.env.example**
   - 移除 `OPENAI_SYSTEM_PROMPT`
   - `OPENAI_MODE` → `MODE`

2. **bridge.py**
   - 移除 `system_prompt` 参数
   - `os.getenv("OPENAI_MODE")` → `os.getenv("MODE")`
   - 移除 `system_prompt` 相关逻辑

3. **narrator-mcp/server.py**
   - 移除 `session.system_prompt` 相关代码
   - 简化 prompt 选择逻辑（只基于 mode）

4. **narrator-mcp/session.py**
   - 移除 `system_prompt` 字段

## 升级指南

如果你之前使用了 `OPENAI_MODE` 或 `OPENAI_SYSTEM_PROMPT`：

### 迁移步骤

1. **更新 .env 文件**:
   ```bash
   # 之前
   OPENAI_MODE=chat
   # 现在
   MODE=chat
   ```

2. **如果使用了自定义 system prompt**:
   - 移除 `OPENAI_SYSTEM_PROMPT`
   - 现在只能使用两种预设模式：chat 或 narration

3. **测试**:
   ```bash
   uv run python bridge.py echo "Hello"
   ```

## 配置优先级（简化后）

```
MODE 环境变量
  ↓
  chat → CHAT_MODE_SYSTEM_PROMPT
  narration → NARRATION_MODE_SYSTEM_PROMPT
  未设置 → chat (默认)
```

## 总结

✅ **更简洁**: 只需要 `MODE=chat` 或 `MODE=narration`
✅ **更清晰**: 没有复杂的优先级
✅ **更易用**: 两种预设模式覆盖大部分场景

**完整配置示例**:
```bash
# .env
OPENAI_API_KEY=sk-your-key-here
OPENAI_MODEL=gpt-4o-mini
OPENAI_VOICE=alloy
MODE=chat
```

就这么简单！🎉
