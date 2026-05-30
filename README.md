# BilibiliUltra

> B站视频内容密度分析器 — 信息密度热力图 + 广告自动跳过

**作者：[高小桥](https://github.com/Xo776) & [GitHub Copilot](https://github.com/features/copilot)**

---

## 这是什么？

一个 Chrome 扩展 + Python 分析后端。打开 B站 视频后，在进度条上方显示 **信息密度热力图**（绿色=干货、灰色=废话、红色=广告），并 **自动跳过广告段**。

<video src="demo.mp4" controls></video>

### 效果预览

```
进度条上方的热力图:
████████░░░░████████████░░░████████░░███
  绿色      灰色        红色
  (干货)   (低密度)    (广告)
```

---

## 功能特点

- 🌡️ **信息密度热力图** — Canvas 渲染在 B站播放器进度条正上方
- 🔇 **广告自动跳过** — 检测到广告段自动 `video.currentTime` 跳转
- 💬 **悬停摘要** — 鼠标悬停热力图显示片段内容摘要
- 🆓 **多层免费信号** — 优先用 B站自身数据（弹幕/章节/字幕），省 LLM 调用
- 🔌 **LLM 后端可换** — OpenAI 兼容接口 / Anthropic Claude / Google Gemini，一个环境变量切换
- 🎵 **Groq Whisper ASR** — 无字幕视频自动语音转文字（免费额度）
- ⚡ **24h 本地缓存** — 同一视频不重复分析

---

## 架构原理

```
┌──────────────────────────────────────────────┐
│                Chrome 扩展 (前端)              │
│                                              │
│  popup.html    →  输入BV号, 开关控制           │
│  content.js    →  热力图Canvas, auto-skip     │
│       │                    ↑                  │
│       │ fetch             │ analysis.json     │
└───────┼────────────────────┼──────────────────┘
        │                    │
┌───────▼────────────────────┴──────────────────┐
│          Python 后端 (server.py)               │
│                                                │
│  第0层: B站免费信号 (毫秒级)                     │
│    ├─ 视频章节 → 广告关键词匹配                  │
│    ├─ 简介时间戳 → 标签"赞助/恰饭"               │
│    ├─ 官方字幕 → 关键词聚类                      │
│    ├─ 弹幕时间码 → "5:30" "705工程"             │
│    └─ 弹幕关键词 → "广告来了" "欢迎回来"         │
│                                                │
│  第1层: 文本获取                                 │
│    ├─ 有字幕 → 直接使用 (免费)                   │
│    └─ 无字幕 → Groq Whisper ASR (免费额度)       │
│                                                │
│  第2层: LLM 分析 (仅正常内容段)                   │
│    ├─ OpenAI 兼容 (DeepSeek/Zhipu/Ollama...)    │
│    ├─ Anthropic Claude                          │
│    └─ Google Gemini                             │
│                                                │
│  输出: analysis.json → segs[{density, is_ad}]   │
└────────────────────────────────────────────────┘
```

### 五层免费信号检测（来自 BiliSmartSkip 的思路）

| 层级 | 信号来源 | 置信度 | 原理 |
|------|---------|-------|------|
| 1 | UP主章节标记 | ⭐⭐⭐⭐⭐ | UP主自己标了"广告"章节 |
| 2 | 视频简介 | ⭐⭐⭐⭐ | 简介时间戳含"赞助/恰饭" |
| 3 | 官方字幕 | ⭐⭐⭐⭐ | 字幕文本关键词聚类 |
| 4 | 弹幕时间码 | ⭐⭐⭐ | 弹幕里大量"5:30""705工程" |
| 5 | 弹幕关键词 | ⭐⭐⭐ | "广告来了" + "欢迎回来"双向锚定 |

任意一层命中 → 直接标记广告，跳过 LLM 调用，省时省钱。

---

## 安装与使用

### 1. 获取 API Key（免费）

| 服务 | 用途 | 注册地址 |
|------|------|---------|
| Groq Whisper | ASR 语音转文字 | https://console.groq.com/keys |
| DeepSeek | LLM 内容分析 | https://platform.deepseek.com/api_keys |
| Anthropic | 备选 LLM | https://console.anthropic.com/ |
| Google Gemini | 备选 LLM | https://aistudio.google.com/apikey |

### 2. 启动后端

```powershell
git clone https://github.com/Xo776/BilibiliUltra.git
cd BilibiliUltra

# 设置 API Key
$env:OPENAI_API_KEY = "sk-xxx"      # DeepSeek Key (默认)
$env:GROQ_API_KEY = "gsk_xxx"      # Groq Whisper Key

# 切换 LLM 后端 (可选)
# $env:LLM_PROVIDER = "anthropic"
# $env:ANTHROPIC_API_KEY = "sk-ant-xxx"

pip install requests
python server.py
# → http://localhost:8765
```

### 3. 加载扩展

1. 打开 `chrome://extensions`
2. 右上角开启 **开发者模式**
3. 点击 **加载已解压的扩展程序**
4. 选择 `extension/` 目录

### 4. 使用

1. 打开任意 B站 视频页面
2. 点击浏览器工具栏的插件图标
3. 填入 API Key → 点 **保存设置**
4. 进度条上方自动出现热力图，广告段自动跳过

> **不需要手动输入 BV号** — 打开视频即自动分析。

---

## LLM 后端切换

```powershell
# DeepSeek (默认)
$env:OPENAI_BASE_URL = "https://api.deepseek.com"
$env:OPENAI_MODEL = "deepseek-chat"

# Ollama 本地 (免费)
$env:OPENAI_BASE_URL = "http://localhost:11434/v1"
$env:OPENAI_MODEL = "qwen2.5:7b"

# Zhipu 智谱
$env:OPENAI_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
$env:OPENAI_MODEL = "glm-4-flash"

# Anthropic Claude
$env:LLM_PROVIDER = "anthropic"
$env:ANTHROPIC_API_KEY = "sk-ant-xxx"
```

---

## 项目结构

```
BilibiliUltra/
├── extension/                     ← Chrome 插件
│   ├── manifest.json              # MV3 配置
│   ├── popup.html                 # 控制面板 UI
│   ├── popup.js                   # 开关逻辑 + 通信
│   ├── content.js                 # 注入B站: 热力图 + 跳过
│   └── icons/
├── server.py                      # 本地 HTTP 桥接
├── config.py                      # LLM 配置 (三路后端)
├── audio_extractor.py             # B站 DASH 音频提取
├── bilibili_signals.py            # 五层免费信号采集
├── content_analyzer.py            # 集成分析管道
└── test_signals.py                # 测试
```

---

## 技术参考

- [BiliSmartSkip](https://github.com/wzy403/BiliSmartSkip) — 五层弹幕+章节广告检测思路
- [VideoAdGuard](https://github.com/Warma10032/VideoAdGuard) — Groq Whisper ASR + LLM 广告检测
- [Immersive Translate](https://immersivetranslate.com/) — Chrome 扩展注入与进度条叠加参考
- [B站下载助手](https://chromewebstore.google.com/detail/ecpppfmdhkopohdmplcafmbfoggijcpe) — DASH 音频流提取参考

---

## 开源协议

MIT License — 随便拿走，随便改，随便用。

---

<p align="center">
  <sub>Made with ❤️ by 高小桥 & GitHub Copilot | 2026</sub>
</p>
