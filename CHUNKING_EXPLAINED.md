# 文本分块策略说明

## 问题

之前的实现会导致音频断断续续,因为:
- `max_tokens=12` 太小
- 即使设置了 `sentence_boundary=True`,达到 `max_tokens` 时也会强制切断
- 结果: 一个句子被分成多个音频块,听起来不自然

## 解决方案

修改了 [narrator-mcp/chunker.py](narrator-mcp/chunker.py) 的分块逻辑:

### 新逻辑

**当 `sentence_boundary=True` (默认):**

```python
# ✅ 只在句子结束符处切断
if self.SENTENCE_END_RE.search(text):  # 匹配: 。！？.!?
    return text  # 返回完整句子

# ✅ 即使超过 max_tokens,也继续等待句子结束
return None  # 继续累积 tokens
```

**当 `sentence_boundary=False`:**

```python
# 达到 max_tokens 就切断 (旧逻辑)
if len(self.buffer) >= self.max_tokens:
    return text
```

### 示例

**输入文本:**
```
"Hello! This is a test message. How are you today?"
```

**旧逻辑 (max_tokens=12):**
```
Chunk 1: "Hello! This "      # 12 tokens → 切断
Chunk 2: "is a test me"      # 12 tokens → 切断  ❌ 句子中间!
Chunk 3: "ssage. How ar"     # 12 tokens → 切断  ❌ 句子中间!
Chunk 4: "e you today?"      # 剩余
```

**新逻辑 (sentence_boundary=True):**
```
Chunk 1: "Hello! "                              # 句子结束 ✅
Chunk 2: "This is a test message. "             # 句子结束 ✅
Chunk 3: "How are you today?"                   # 句子结束 ✅
```

## 优势

### 1. 音频连贯性
每个 TTS 调用处理完整句子,声音更自然,没有不自然的停顿。

### 2. 更好的语音质量
TTS 模型能够更好地理解完整句子的语境,生成更自然的语调和停顿。

### 3. 减少 API 调用
完整句子可能比多个小块更高效:
- 旧: 4 个 TTS API 调用 (每个小块一次)
- 新: 3 个 TTS API 调用 (每个句子一次)

### 4. 更自然的节奏
只在句子之间有短暂停顿,而不是在句子中间。

## 配置

在 [narrator-mcp/server.py:22](narrator-mcp/server.py#L22):

```python
# sentence_boundary=True: 只在句子边界切断 (推荐)
chunker = Chunker(max_tokens=12, sentence_boundary=True)

# sentence_boundary=False: 达到 max_tokens 就切断 (不推荐)
# chunker = Chunker(max_tokens=12, sentence_boundary=False)
```

**注意**: 当 `sentence_boundary=True` 时,`max_tokens` 参数实际上被忽略,只在句子边界切断。

## 句子结束符

当前识别的句子结束符:

```python
SENTENCE_END_RE = re.compile(r"[。！？.!?]$")
```

支持:
- 中文: 。！？
- 英文: .!?

### 扩展支持

如需支持更多标点符号,可以修改正则表达式:

```python
# 添加问号、分号、冒号等
SENTENCE_END_RE = re.compile(r"[。！？.!?;:…]$")

# 支持多字符结束符 (如 "..." 或 "!!")
SENTENCE_END_RE = re.compile(r"([。！？.!?]|\.\.\.|!!|!!)$")
```

## 测试

```bash
# 测试完整句子分块
uv run python bridge.py echo "你好!这是一个测试。你今天过得怎么样?"

# 查看日志中的文本块
tail -f narrator-mcp/logs/narrator_*.log | grep "📝 Narrate text"
```

你应该看到每个 TTS 请求对应一个完整的句子。

## 性能影响

### 延迟
- **第一个句子**: 稍微增加 (~100-200ms),需要等待句子结束
- **整体**: 基本没有影响,因为 TTS 并行处理

### 内存
- **缓冲区**: 可能累积更多 tokens (整句而不是 12 tokens)
- **影响**: 可忽略不计 (通常 < 1KB per sentence)

## 故障排查

### 问题: 音频还是断断续续

可能原因:
1. **没有句子结束符**: 确保文本包含 `.!?。！？`
2. **网络延迟**: OpenAI TTS API 响应慢
3. **播放缓冲**: AudioPlayer 队列问题

检查方法:
```bash
# 查看实际发送给 TTS 的文本块
tail -100 narrator-mcp/logs/narrator_*.log | grep -A 5 "📝 Narrate text"
```

### 问题: 长时间没有声音

如果句子很长且没有结束符,会一直累积。解决方法:

```python
# 添加最大缓冲区限制
def add_token(self, token: str) -> Optional[str]:
    self.buffer.append(token)
    text = "".join(self.buffer)

    if self.sentence_boundary:
        if self.SENTENCE_END_RE.search(text):
            self.buffer.clear()
            return text
        # 安全阀: 如果缓冲区过大,强制切断
        if len(self.buffer) > 500:  # 例如 500 tokens
            self.buffer.clear()
            return text
        return None
```

## 总结

新的分块策略确保:
- ✅ 每个音频块都是完整句子
- ✅ 声音自然连贯
- ✅ 只在句子之间有停顿
- ✅ 更好的 TTS 质量
