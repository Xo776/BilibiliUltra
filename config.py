"""
新项目 - 配置模块
支持 OpenAI 兼容接口 + Anthropic + Gemini
所有 base_url 可配，兼容 DeepSeek / Zhipu / Ollama / 硅基流动 等
"""
import os
import sys
import json

# --- 路径处理：引用父项目的 tools/LLM 模块 ---
_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PARENT)

from config.config import load_api_key

# ============================================================
# LLM 后端选择 — 改这里切换供应商
# ============================================================
# 可选: "openai" | "anthropic" | "gemini"
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")

# ============================================================
# OpenAI 兼容接口 (支持 DeepSeek / Zhipu / Ollama / SiliconFlow 等)
# ============================================================
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or load_api_key("deepseek")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "deepseek-v4-flash")

# 常用 base_url 速查:
#   DeepSeek:    https://api.deepseek.com
#   Zhipu (智谱): https://open.bigmodel.cn/api/paas/v4
#   Ollama 本地:  http://localhost:11434/v1
#   SiliconFlow: https://api.siliconflow.cn/v1
#   Groq:         https://api.groq.com/openai/v1
#   OpenAI 官方:  https://api.openai.com/v1

# ============================================================
# Anthropic Claude
# ============================================================
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-3-5-sonnet-20241022")
ANTHROPIC_VERSION = "2023-06-01"  # Anthropic API version header

# ============================================================
# Gemini (复用父项目)
# ============================================================
GEMINI_KEY = load_api_key("gemini")

# 兼容旧代码
DEEPSEEK_KEY = load_api_key("deepseek")

# --- ASR 配置 ---
# Groq Whisper (免费额度: 每天 ~2小时音频)
# 注册: https://console.groq.com
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_WHISPER_MODEL = "whisper-large-v3-turbo"  # 或 "distil-whisper-large-v3-en"

# --- 分析配置 ---
# 每个 segment 的时长（秒）
SEGMENT_DURATION = 30

# 信息密度 + 广告检测 prompt (一次性全文字幕分析)
DENSITY_PROMPT = """你是B站视频内容分析专家。以下是一个视频的完整字幕(带时间戳)，请分析:

## 任务
1. **广告检测**: 找出所有广告/赞助/推广/恰饭段落
2. **信息密度**: 对每个30秒区间评分(1-10)

## 广告特征 (B站常见)
- "感谢金主/赞助商/甲方爸爸"
- "本视频由...赞助/支持"
- "下载链接在评论区/简介"
- "三连/点赞/投币/关注/充电" 密集区
- "优惠券/折扣码/下单/购买"
- "加群/微信/公众号" 推广
- 突然从干货切换到商业推广的语气转变
- 视频开头/结尾的频道推广

## 信息密度评分标准
- 10: 纯干货, 密集知识/观点输出
- 7-9: 主要内容, 正常叙述
- 4-6: 过渡/铺垫/举例
- 1-3: 废话/重复/寒暄/凑时长

## 输出格式 (严格JSON, 不要markdown包裹)
{
  "ad_segments": [
    {"start": 120, "end": 155, "reason": "感谢赞助商+优惠券推广"}
  ],
  "density_map": [
    {"start": 0, "end": 30, "density": 8, "summary": "核心观点引入"},
    {"start": 30, "end": 60, "density": 7, "summary": "案例分析"}
  ]
}

density_map 必须覆盖整个视频时长，每个区间30秒。

字幕内容:
{transcript}"""

# 仅密度评分 prompt (轻量, 用于对单个片段微调)
DENSITY_SINGLE_PROMPT = """你是内容分析专家。分析以下视频字幕片段，给出两个评分(1-10):

1. **信息密度**: 10=纯干货, 1=纯废话/寒暄/重复
2. **广告概率**: 10=明显是赞助/推广/带货/求三连, 1=正常内容

只返回JSON格式, 不要其他文字:
{"density": 7, "ad_probability": 1, "summary": "10字以内摘要"}"""

# --- 输出路径 ---
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
