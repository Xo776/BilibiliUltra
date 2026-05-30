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
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "deepseek-chat")

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

# 信息密度评分 prompt
DENSITY_PROMPT = """你是内容分析专家。分析以下视频字幕片段，给出两个评分(1-10):

1. **信息密度**: 10=纯干货, 1=纯废话/寒暄/重复
2. **广告概率**: 10=明显是赞助/推广/带货/求三连, 1=正常内容

只返回JSON格式, 不要其他文字:
{"density": 7, "ad_probability": 1, "summary": "10字以内摘要"}"""

# --- 输出路径 ---
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
