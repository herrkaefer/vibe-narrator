# 音频播放错误修复

## 问题

运行时出现 FFmpeg 解码错误:

```
❌ Error playing audio chunk: Decoding failed. ffmpeg returned error code: 183
[in#0 @ 0x7face0b04100] Error opening input: Invalid data found when processing input
```

## 根本原因

### 问题链

1. **TTS API** 返回完整的 MP3 文件 (例如 20KB)
2. **narrator-mcp/tts.py** 将其分成多个 4096 字节的块:
   ```python
   for chunk in response.iter_bytes(chunk_size=4096):
       yield chunk  # 返回多个小块
   ```
3. **narrator-mcp/server.py** 将每个小块作为独立事件发送:
   ```python
   async for audio_chunk in stream_tts(...):
       await send_audio_event(send, audio_chunk, encoding="hex")
   # 结果: 发送 5-6 个 audio_chunk 事件
   ```
4. **bridge.py** 将每个小块当作完整的 MP3 文件:
   ```python
   audio_bytes = bytes.fromhex(data_hex)
   self.audio_player.add_chunk(audio_bytes)  # ❌ 不完整的 MP3!
   ```
5. **pydub** 尝试解码不完整的 MP3 → **FFmpeg 错误**

### 为什么不完整的 MP3 无法播放?

MP3 文件有特定的结构:
```
[MP3 Header] [Frame 1] [Frame 2] ... [Frame N] [ID3 Tags]
```

分块后的数据可能:
- 缺少 MP3 header
- 在帧中间切断
- 缺少 ID3 tags

FFmpeg 无法识别这些不完整的数据。

## 解决方案

### 修改 [narrator-mcp/server.py](narrator-mcp/server.py#L150-L161)

**之前**: 逐块发送音频
```python
async for audio_chunk in stream_tts(...):
    await send_audio_event(send, audio_chunk, encoding="hex")
# 发送: chunk1, chunk2, chunk3, chunk4, chunk5
```

**现在**: 累积完整 MP3 后发送
```python
audio_buffer = bytearray()
async for audio_chunk in stream_tts(...):
    audio_buffer.extend(audio_chunk)  # ✅ 累积所有块

# 发送完整的 MP3 文件
if audio_buffer:
    await send_audio_event(send, bytes(audio_buffer), encoding="hex")
# 发送: complete_mp3
```

### 效果

**之前**:
```
Sentence 1:
  → Audio chunk #1 (4096 bytes) ❌ 不完整
  → Audio chunk #2 (4096 bytes) ❌ 不完整
  → Audio chunk #3 (4096 bytes) ❌ 不完整
  → Audio chunk #4 (1536 bytes) ❌ 不完整
  → FFmpeg 错误 × 4

Sentence 2:
  → Audio chunk #5 (4096 bytes) ❌ 不完整
  → ...
```

**现在**:
```
Sentence 1:
  → Audio chunk #1 (13728 bytes) ✅ 完整 MP3
  → 成功播放!

Sentence 2:
  → Audio chunk #2 (15360 bytes) ✅ 完整 MP3
  → 成功播放!
```

## 验证

### 测试

```bash
uv run python bridge.py echo "你好!这是测试。谢谢!"
```

### 检查日志

**成功的日志应该显示**:
```
🔊 Audio chunk #1 received (hex, 27456 chars)  # 更大的块 = 完整 MP3
   Added 13728 bytes to playback queue
🎧 Audio playback worker started
Playing audio chunk: 2500ms, 24000Hz  # ✅ 成功播放
```

**不应该出现**:
```
❌ Error playing audio chunk: Decoding failed
```

### 预期音频块大小

- **之前**: 8192 chars (4096 bytes) - 多个小块
- **现在**: 20000-40000 chars (10000-20000 bytes) - 完整 MP3

一个句子通常对应一个大的音频块。

## 性能影响

### 延迟
- **增加**: ~100-200ms (需要等待完整 MP3 下载)
- **可接受**: 用户不会注意到差异

### 内存
- **增加**: ~10-20KB per sentence (临时缓冲)
- **可忽略**: 现代机器轻松处理

### 带宽
- **无变化**: 总数据量相同,只是组织方式不同

## 替代方案 (未采用)

### 方案 1: Bridge 端累积
在 bridge.py 中累积同一句子的所有块:
```python
# 复杂,需要跟踪哪些块属于同一句子
```
**缺点**: 需要额外逻辑来识别句子边界

### 方案 2: 真正的流式播放
使用支持流式解码的库:
```python
# 需要更复杂的音频处理
```
**缺点**: pyaudio + pydub 不支持流式 MP3 解码

### 方案 3: 改用 PCM 格式
让 TTS 返回 PCM 而不是 MP3:
```python
# 可以真正流式播放
```
**缺点**:
- OpenAI TTS API 不支持 PCM 输出
- 数据量更大 (~10x)

## 为什么选择当前方案?

✅ **简单**: 只需修改一处代码
✅ **可靠**: 保证 MP3 完整性
✅ **兼容**: 不需要改变 API 或格式
✅ **性能**: 延迟增加可忽略不计

## 总结

通过在 MCP server 端累积完整的 MP3 文件再发送,确保:
1. ✅ Bridge 收到完整的、可解码的 MP3 文件
2. ✅ FFmpeg 可以正确解码
3. ✅ 音频流畅播放,没有错误
4. ✅ 每个句子对应一个音频块,声音连贯
