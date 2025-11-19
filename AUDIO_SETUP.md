# 音频播放设置指南

## 概述

Vibe Narrator 现在支持**实时流式音频播放**! 当 MCP server 生成音频时,会立即通过扬声器播放出来。

## 系统要求

### macOS (推荐)

macOS 通常已经包含所需的音频库:

```bash
# 如果遇到问题,可以通过 Homebrew 安装 portaudio
brew install portaudio
```

### Linux (Ubuntu/Debian)

```bash
# 安装 PortAudio 开发库
sudo apt-get update
sudo apt-get install portaudio19-dev python3-pyaudio

# 可选: 安装 FFmpeg (用于更好的音频格式支持)
sudo apt-get install ffmpeg
```

### Linux (Fedora/RHEL)

```bash
sudo dnf install portaudio-devel
```

### Windows

Windows 用户通常不需要额外步骤,但如果遇到问题:

1. 下载并安装 [Microsoft Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe)
2. 运行 `uv sync` 重新安装依赖

## 安装

```bash
# 安装 Python 依赖
uv sync
```

## 测试音频播放

```bash
# 快速测试
./quick_test.sh

# 完整测试
./test_echo.sh
```

如果看到这样的日志,说明音频播放正常:

```
🔊 PyAudio initialized successfully
🎵 Audio playback started
🔊 Audio chunk #1 received (hex, 16384 chars)
   Added 8192 bytes to playback queue
🎧 Audio playback worker started
Playing audio chunk: 2500ms, 24000Hz
```

## 故障排查

### 问题: "PyAudio not available - audio playback disabled"

这说明 PyAudio 未正确安装。解决方法:

```bash
# macOS
brew install portaudio
uv sync

# Linux
sudo apt-get install portaudio19-dev
uv sync
```

### 问题: 听不到声音

1. **检查系统音量**: 确保系统音量未静音
2. **检查日志**:
   ```bash
   tail -f $(ls -t logs/bridge_*.log | head -1) | grep "🔊\\|🎵\\|🎧"
   ```
3. **测试系统音频**: 播放其他音频文件确认扬声器工作正常

### 问题: 音频断断续续

可能是网络或 OpenAI API 响应慢。解决方法:

1. 检查网络连接
2. 尝试使用更快的模型 (在 `.env` 中设置 `OPENAI_MODEL=gpt-4o-mini`)
3. 查看日志中的 API 响应时间

### 问题: "Error playing audio chunk"

查看完整错误信息:

```bash
tail -100 $(ls -t logs/bridge_*.log | head -1) | grep -A 5 "Error playing"
```

常见原因:
- FFmpeg 未安装 (Linux 用户需要安装 `ffmpeg`)
- 音频格式问题
- 音频设备被其他程序占用

## 禁用音频播放

如果不需要音频播放,程序会自动检测并禁用:

```
🔇 Audio playback disabled (PyAudio not available)
```

所有其他功能仍然正常工作,只是不会播放声音。

## 高级配置

### 调整音频播放队列

编辑 `audio_player.py` 中的参数:

```python
# 调整播放块大小 (默认 4096 字节)
for chunk in response.iter_bytes(chunk_size=8192):
```

### 保存音频到文件

在 `bridge.py` 的音频块处理中添加:

```python
# 保存到文件
import datetime
filename = f"output_{datetime.datetime.now().strftime('%H%M%S')}_{self.audio_chunks_received}.mp3"
with open(filename, "wb") as f:
    f.write(audio_bytes)
logger.info(f"💾 Saved audio to {filename}")
```

## 架构

```
MCP Server (OpenAI TTS)
    ↓ MP3 chunks (hex-encoded)
Bridge (_listen_stdout)
    ↓ Decode hex to bytes
AudioPlayer (Queue)
    ↓ Background thread
PyAudio + pydub
    ↓
System Audio Output 🔊
```

## 性能

- **延迟**: 通常 < 500ms (从文本到开始播放)
- **缓冲**: 使用队列确保流畅播放
- **线程安全**: 播放在独立线程,不阻塞主程序

## 支持的平台

| 平台 | 状态 | 备注 |
|------|------|------|
| macOS | ✅ 完全支持 | 推荐 |
| Linux | ✅ 完全支持 | 需要 portaudio |
| Windows | ✅ 支持 | 可能需要 VC++ Redistributable |
| WSL2 | ⚠️  有限支持 | 需要配置音频输出 |

## 下一步

- 🎛️  添加音量控制
- ⏸️  添加暂停/恢复功能
- 💾 可选的音频文件保存
- 🎚️  音频可视化

## 反馈

遇到问题? 请查看日志并提供:
1. 操作系统版本
2. Bridge 日志 (`logs/bridge_*.log`)
3. 错误信息
