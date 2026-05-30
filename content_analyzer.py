"""
内容分析模块 — 集成版

全管道 (从快到慢, 从免费到付费):
  ┌─ 第0层: B站原生信号 (免费, 100ms级)
  │   ├─ 章节标记 + 简介时间戳 + 官方字幕 + 弹幕时间码 + 弹幕关键词
  │   └─ 命中 → 直接标记广告, 跳过 LLM
  ├─ 第1层: 关键词预筛 (免费, 毫秒级)
  │   └─ 字幕文本含"三连/赞助/下单" → 标记广告
  ├─ 第2层: Groq Whisper ASR (免费额度, 分钟级)
  │   └─ 无官方字幕时启用
  └─ 第3层: DeepSeek LLM (付费, 秒级)
      └─ 信息密度评分 + 广告二次确认
  → 输出 analysis.json (供 Chrome 扩展消费)
"""
import json
import os
import sys
import time
from typing import Optional

# 复用父项目 LLM 客户端
_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PARENT)

from config import (
    LLM_PROVIDER,
    OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL,
    ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, ANTHROPIC_MODEL, ANTHROPIC_VERSION,
    GEMINI_KEY,
    GROQ_API_KEY, GROQ_WHISPER_MODEL,
    SEGMENT_DURATION, DENSITY_PROMPT, OUTPUT_DIR,
)

# B站免费信号模块
from bilibili_signals import (
    collect_all, get_best_ad_segment,
    AD_START_KEYWORDS, AD_END_KEYWORDS, AD_GENERAL_KEYWORDS,
    AD_CONTENT_KEYWORDS, AD_CHAPTER_KEYWORDS, BiliSignals,
)


# ============================================================
# 步骤1: ASR 转录 (Groq Whisper — 免费, 每分钟约 0.03元等值)
# ============================================================

def transcribe(audio_path: str) -> dict:
    """
    调用 Groq Whisper API 转录音频
    
    Returns:
        {"text": "完整文本", "segments": [{start, end, text}, ...]}
    """
    if not GROQ_API_KEY:
        raise RuntimeError("请设置 GROQ_API_KEY 环境变量\n"
                           "免费获取: https://console.groq.com/keys")

    print(f"[ASR] 正在转录: {os.path.basename(audio_path)} ...")

    with open(audio_path, "rb") as f:
        import requests
        resp = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            files={"file": f},
            data={
                "model": GROQ_WHISPER_MODEL,
                "response_format": "verbose_json",
                "language": "zh",           # 中文为主, 自动检测
                "timestamp_granularities[]": "segment",
            },
            timeout=300,
        )

    if resp.status_code != 200:
        raise RuntimeError(f"ASR 失败: {resp.status_code} {resp.text}")

    result = resp.json()
    print(f"[ASR] 转录完成: {len(result.get('text', ''))} 字符, "
          f"{len(result.get('segments', []))} 个片段")

    return result


# ============================================================
# LLM 后端 (三路: OpenAI 兼容 / Anthropic / Gemini)
# ============================================================

def _ask_llm(prompt: str) -> dict:
    """根据 LLM_PROVIDER 配置自动选择后端"""
    if LLM_PROVIDER == "anthropic":
        return _ask_claude(prompt)
    elif LLM_PROVIDER == "gemini":
        return _ask_gemini(prompt)
    else:
        return _ask_openai_compatible(prompt)


def _ask_openai_compatible(prompt: str) -> dict:
    """
    OpenAI 兼容 API (DeepSeek / Zhipu / Ollama / SiliconFlow / Groq ...)
    
    设置环境变量切换:
      OPENAI_API_KEY=xxx
      OPENAI_BASE_URL=https://api.deepseek.com
      OPENAI_MODEL=deepseek-chat
    """
    import requests
    resp = requests.post(
        f"{OPENAI_BASE_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": OPENAI_MODEL,
            "messages": [
                {"role": "system", "content": DENSITY_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 200,
        },
        timeout=30,
    )
    data = resp.json()
    return _parse_llm_response(data["choices"][0]["message"]["content"])


def _ask_claude(prompt: str) -> dict:
    """
    Anthropic Claude API
    
    设置环境变量:
      ANTHROPIC_API_KEY=xxx
      ANTHROPIC_BASE_URL=https://api.anthropic.com    (默认)
      ANTHROPIC_MODEL=claude-haiku-3-5-sonnet-20241022
    """
    import requests
    resp = requests.post(
        f"{ANTHROPIC_BASE_URL}/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        },
        json={
            "model": ANTHROPIC_MODEL,
            "system": DENSITY_PROMPT,
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 200,
        },
        timeout=30,
    )
    data = resp.json()
    return _parse_llm_response(data["content"][0]["text"])


def _ask_gemini(prompt: str) -> dict:
    """Google Gemini API (via OpenAI compatible endpoint)"""
    import requests
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
        params={"key": GEMINI_KEY},
        headers={"Content-Type": "application/json"},
        json={
            "system_instruction": {"parts": [{"text": DENSITY_PROMPT}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 200},
        },
        timeout=30,
    )
    data = resp.json()
    return _parse_llm_response(data["candidates"][0]["content"]["parts"][0]["text"])


def _parse_llm_response(text: str) -> dict:
    """从 LLM 回复中提取 JSON"""
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试从 ```json ... ``` 中提取
    import re
    m = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
    if m:
        return json.loads(m.group(1))

    # 尝试找到第一个 { ... }
    m = re.search(r'\{[\s\S]*\}', text)
    if m:
        return json.loads(m.group(0))

    # 兜底
    return {"density": 5, "ad_probability": 1, "summary": "解析失败"}


def _merge_segments(segments: list, seg_duration: int = SEGMENT_DURATION) -> list:
    """
    将 ASR 返回的细粒度 segments 合并为固定时长的分析块
    
    Args:
        segments: ASR segments [{start, end, text}, ...]
        seg_duration: 每个分析块时长(秒)
    
    Returns:
        [{start, end, text, duration}, ...]
    """
    if not segments:
        return []

    merged = []
    current = {"start": 0, "end": seg_duration, "text": "", "duration": seg_duration}

    for seg in segments:
        seg_start = seg.get("start", 0)
        seg_end = seg.get("end", seg_start + 1)
        seg_mid = (seg_start + seg_end) / 2

        # 找到当前 segment 属于哪个分析块
        while seg_mid >= current["end"]:
            merged.append(current)
            new_start = current["end"]
            current = {
                "start": new_start,
                "end": new_start + seg_duration,
                "text": "",
                "duration": seg_duration,
            }

        current["text"] += seg.get("text", "") + " "

    # 最后一个块
    if current["text"].strip():
        merged.append(current)

    return merged


def _is_in_ad_zone(seg_start: float, seg_end: float, bili_signals: Optional[BiliSignals]) -> bool:
    """检查当前片段是否落在 B站原生信号检测到的广告段内"""
    if not bili_signals:
        return False
    best = get_best_ad_segment(bili_signals)
    if not best:
        return False
    # 有重叠即判定为广告区
    return not (seg_end <= best["start"] or seg_start >= best["end"])


def _skip_ad_indicator(text: str) -> bool:
    """快速预筛选：使用 BiliSmartSkip 关键词库检测广告特征"""
    all_kw = AD_START_KEYWORDS + AD_END_KEYWORDS + AD_GENERAL_KEYWORDS + AD_CONTENT_KEYWORDS
    text_lower = text.lower()
    hits = sum(1 for kw in all_kw if kw in text_lower)
    if hits >= 3:
        return True
    if len(text) < 100 and hits >= 2:
        return True
    return False


def analyze(segments: list, total_duration: int, bili_signals: Optional[BiliSignals] = None) -> list:
    """
    对每个时间块进行评分 (关键词预筛 → B站信号 → LLM)
    
    Args:
        segments: _merge_segments 的输出
        total_duration: 视频总时长(秒)
        bili_signals: B站原生信号 (可选)
    
    Returns:
        [{start, end, density, ad_probability, summary, is_ad, source}, ...]
    """
    results = []
    total = len(segments)
    skipped_llm = 0

    for i, seg in enumerate(segments):
        text = seg["text"].strip()
        start = seg["start"]
        end = min(seg["end"], total_duration)

        # 空片段 → 默认低密度
        if not text:
            results.append({
                "start": start, "end": end,
                "density": 1, "ad_probability": 0,
                "summary": "静音/无内容", "is_ad": False,
                "source": "silence",
            })
            print(f"  [{i+1}/{total}] {start}-{end}s: 静音 → 跳过")
            continue

        # 预筛选 1: B站原生信号 → 直接标记广告 (最高置信度)
        if _is_in_ad_zone(start, end, bili_signals):
            results.append({
                "start": start, "end": end,
                "density": 2, "ad_probability": 10,
                "summary": "广告(B站原生信号)", "is_ad": True,
                "source": "bili_signal",
            })
            print(f"  [{i+1}/{total}] {start}-{end}s: 广告(B站信号) → 跳过 LLM")
            skipped_llm += 1
            continue

        # 预筛选 2: 关键词 → 直接标记广告
        if _skip_ad_indicator(text):
            results.append({
                "start": start, "end": end,
                "density": 3, "ad_probability": 8,
                "summary": "广告(关键词匹配)", "is_ad": True,
                "source": "keyword",
            })
            print(f"  [{i+1}/{total}] {start}-{end}s: 广告(关键词) → 跳过 LLM")
            skipped_llm += 1
            continue

        # LLM 评分 (信息密度 + 广告二次确认)
        print(f"  [{i+1}/{total}] {start}-{end}s: 分析中... [{LLM_PROVIDER}]")
        try:
            llm_result = _ask_llm(text[:2000])
        except Exception as e:
            print(f"    LLM 调用失败: {e}")
            llm_result = {"density": 5, "ad_probability": 1, "summary": "LLM错误"}

        results.append({
            "start": start,
            "end": end,
            "density": llm_result.get("density", 5),
            "ad_probability": llm_result.get("ad_probability", 1),
            "summary": llm_result.get("summary", ""),
            "is_ad": llm_result.get("ad_probability", 1) >= 7,
            "source": "llm",
        })
        time.sleep(0.3)

    if skipped_llm > 0:
        print(f"  💰 省了 {skipped_llm} 次 LLM 调用 (免费信号命中)")

    return results


# ============================================================
# 步骤3: 生成输出 JSON
# ============================================================

def build_output(video_info, asr_result: dict, analysis: list,
                  bili_signals: Optional[BiliSignals] = None) -> dict:
    """构建最终输出 JSON"""
    best_ad = get_best_ad_segment(bili_signals) if bili_signals else None

    return {
        "meta": {
            "bvid": video_info.bvid if hasattr(video_info, 'bvid') else "",
            "title": video_info.title if hasattr(video_info, 'title') else "",
            "duration": sum(seg["duration"] for seg in analysis),
            "total_segments": len(analysis),
            "llm_provider": LLM_PROVIDER,
            "llm_model": OPENAI_MODEL if LLM_PROVIDER != "anthropic" else ANTHROPIC_MODEL,
        },
        "signals": {
            "bili_native": {
                "chapter": bili_signals.ad_from_chapter if bili_signals else None,
                "description": bili_signals.ad_from_description if bili_signals else None,
                "subtitle": bili_signals.ad_from_subtitle if bili_signals else None,
                "danmaku_time": bili_signals.ad_from_danmaku_time if bili_signals else None,
                "danmaku_kw": bili_signals.ad_from_danmaku_kw if bili_signals else None,
            },
            "best_bili_signal": best_ad,
        },
        "segments": analysis,
        "ad_segments": [
            {"start": s["start"], "end": s["end"]}
            for s in analysis if s.get("is_ad")
        ],
    }


# ============================================================
# 一键入口
# ============================================================

def run(audio_path: str = None, video_info=None, bvid: str = None, cid: int = None,
        output_dir: str = None) -> dict:
    """
    完整分析流程: B站信号 → 字幕/ASR → 分段 → LLM评分 → 输出 JSON
    
    两种模式:
      模式A (有B站URL): bvid+cid → 先采免费信号, 有字幕则跳过ASR
      模式B (纯音频):   audio_path → ASR → LLM分析
    
    Returns:
        分析结果 dict
    """
    output_dir = output_dir or OUTPUT_DIR

    # === 第0层: B站免费信号 ===
    bili_signals = None
    if bvid and cid:
        try:
            duration = video_info.duration if video_info else 300
            bili_signals = collect_all(bvid, cid, duration)
        except Exception as e:
            print(f"[警告] B站信号采集失败: {e}")

    # === 文本来源 ===
    asr_result = None

    if bili_signals and bili_signals.subtitle_body:
        print("[文本] 使用 B站官方字幕 (跳过 ASR)")
        raw_segments = [
            {"start": s.get("from", 0), "end": s.get("to", 0), "text": s.get("content", "")}
            for s in bili_signals.subtitle_body
        ]
    elif audio_path and os.path.exists(audio_path):
        asr_result = transcribe(audio_path)
        raw_segments = asr_result.get("segments", [])
        if not raw_segments:
            full_text = asr_result.get("text", "")
            sentences = full_text.replace("！", "。").replace("？", "。").split("。")
            raw_segments = [
                {"start": i * 5, "end": (i + 1) * 5, "text": s.strip()}
                for i, s in enumerate(sentences) if s.strip()
            ]
    else:
        print("[警告] 无字幕 + 无音频，输出空分析")
        raw_segments = []

    # === 分段 ===
    total_duration = video_info.duration if video_info else (
        int(asr_result.get("duration", 300)) if asr_result else 300
    )
    chunks = _merge_segments(raw_segments)
    print(f"\n[分析] 共 {len(chunks)} 个片段, LLM: {LLM_PROVIDER}/{OPENAI_MODEL}")

    # === LLM 分析 ===
    analysis = analyze(chunks, total_duration, bili_signals)

    # === 输出 ===
    output = build_output(video_info, asr_result or {}, analysis, bili_signals)

    json_path = os.path.join(output_dir, "analysis.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n[完成] analysis.json")
    print(f"  时长: {total_duration}s | 片段: {len(analysis)}")
    print(f"  广告段: {len([s for s in analysis if s.get('is_ad')])}")
    print(f"  高密度: {len([s for s in analysis if s.get('density', 0) >= 7])}")
    print(f"  后端: {LLM_PROVIDER}")

    return output


if __name__ == "__main__":
    import sys
    audio = sys.argv[1] if len(sys.argv) > 1 else "output/test.m4a"
    run(audio_path=audio)
