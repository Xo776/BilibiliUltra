"""
B站原生信号采集模块
来源: BiliSmartSkip 的核心思路 — 零 API 依赖, 用 B站自己的数据做广告检测

五层免费信号:
  1. 视频章节标记 (viewPoints)  — UP主自己标的"广告"章节
  2. 视频简介时间戳 (description) — 简介里的时间列表含"赞助/恰饭"
  3. B站官方字幕 (CC字幕)       — AI/人工字幕中的广告关键词
  4. 弹幕时间码解析 (danmaku)    — "5:30" "705工程" "五分三十秒"
  5. 弹幕关键词匹配 (danmaku)    — "广告来了" "欢迎回来" "正片开始"
"""
import re
import json
import requests
from typing import Optional
from dataclasses import dataclass, field

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com",
}

# ============================================================
# 广告关键词库 (from BiliSmartSkip constants.js)
# ============================================================

AD_START_KEYWORDS = [
    "广告开始", "开始恰饭", "恰饭开始", "广告来了", "开始推广",
    "金主来了", "广告时间", "前方广告", "广告预警", "进入广告",
    "赞助时间", "推广时间", "植入开始",
]

AD_END_KEYWORDS = [
    "广告结束", "欢迎回来", "恰饭结束", "回来了", "广告完了",
    "正片开始", "回归正片", "正片继续", "广告完毕", "继续正片",
    "恰饭完毕", "推广结束",
]

AD_GENERAL_KEYWORDS = [
    "广告", "恰饭", "赞助", "商单", "推广", "软广",
    "金主爸爸", "甲方", "恰个饭", "商务",
]

AD_CONTENT_KEYWORDS = [
    "购买链接", "下单", "优惠券", "折扣码", "评论区",
    "抽奖", "三连", "点赞投币", "关注", "充电",
    "感谢", "本视频由", "感谢大家", "一键三连",
    "订阅频道", "加群", "微信", "公众号",
]

AD_CHAPTER_KEYWORDS = [
    "广告", "ad", "sponsor", "赞助", "商单", "恰饭", "推广",
]

# 中文数字 → 整数
ZH_NUM_MAP = {'零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
              '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}


# ============================================================
# API 调用
# ============================================================

def _get_json(url: str, params: dict = None) -> dict:
    resp = requests.get(url, params=params, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()


def fetch_player_info(bvid: str, cid: int) -> dict:
    """获取播放器信息: 章节标记 和 字幕列表"""
    data = _get_json("https://api.bilibili.com/x/player/v2", {
        "bvid": bvid, "cid": cid,
    })
    if data["code"] != 0:
        return {}
    return data["data"]


def fetch_video_info(bvid: str) -> dict:
    """获取视频描述、duration 等"""
    data = _get_json("https://api.bilibili.com/x/web-interface/view", {
        "bvid": bvid,
    })
    if data["code"] != 0:
        return {}
    return data["data"]


def fetch_subtitle_body(subtitle_url: str) -> list:
    """下载 B站 字幕 JSON"""
    if subtitle_url.startswith("//"):
        subtitle_url = "https:" + subtitle_url
    data = _get_json(subtitle_url)
    return data.get("body", [])


def fetch_danmaku_segment(cid: int, segment_index: int = 1) -> bytes:
    """
    下载弹幕 Protobuf 分段数据
    segment_index: 弹幕每6分钟一段，从1开始
    """
    resp = requests.get(
        f"https://api.bilibili.com/x/v2/dm/web/seg.so",
        params={"oid": cid, "segment_index": segment_index, "type": 1},
        headers=HEADERS,
    )
    resp.raise_for_status()
    return resp.content


# ============================================================
# 弹幕 Protobuf 解码 (简易版, 不依赖外部库)
# ============================================================

def decode_danmaku_proto(buffer: bytes) -> list:
    """
    解码 B站 弹幕 Protobuf 格式 (DmSegMobileReply)
    返回: [{"time": float, "text": str, "mode": int}, ...]
    """
    results = []
    pos = 0
    try:
        while pos < len(buffer):
            tag, pos = _read_varint(buffer, pos)
            field_num = tag >> 3
            wire_type = tag & 0x7

            if wire_type == 0:  # varint
                val, pos = _read_varint(buffer, pos)
            elif wire_type == 2:  # length-delimited
                length, pos = _read_varint(buffer, pos)
                if field_num == 1:  # elems (repeated DanmakuElem)
                    _parse_elems(buffer, pos, length, results)
                pos += length
            else:
                break
    except Exception:
        pass
    return results


def _parse_elems(buf: bytes, start: int, length: int, results: list):
    """解析 repeated DanmakuElem"""
    end = start + length
    pos = start
    current = {}

    while pos < end:
        tag, pos = _read_varint(buf, pos)
        field_num = tag >> 3
        wire_type = tag & 0x7

        if wire_type == 0:
            val, pos = _read_varint(buf, pos)
            if field_num == 1:  # id
                current["id"] = val
            elif field_num == 2:  # progress (ms)
                current["time"] = val / 1000.0
            elif field_num == 3:  # mode
                current["mode"] = val
            elif field_num == 4:  # fontsize
                pass
            elif field_num == 5:  # color
                pass
            elif field_num == 9:  # ctime
                pass
            elif field_num == 10:  # weight
                pass
        elif wire_type == 2:
            length, pos = _read_varint(buf, pos)
            if field_num == 6:  # midHash
                pos += length
            elif field_num == 7:  # content
                current["text"] = buf[pos:pos + length].decode("utf-8", errors="ignore")
                # 一条弹幕解析完成
                if "time" in current and "text" in current:
                    results.append(current)
                current = {}
                pos += length
            elif field_num == 8:  # dmidStr
                pos += length
            else:
                pos += length
        else:
            break


def _read_varint(buf: bytes, pos: int) -> tuple:
    """读取 protobuf varint, 返回 (value, new_pos)"""
    value = 0
    shift = 0
    while pos < len(buf):
        byte = buf[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            break
        shift += 7
    return value, pos


def fetch_all_danmaku(cid: int, duration: int) -> list:
    """
    下载所有分段的弹幕
    每段6分钟
    """
    total_segments = max(1, (duration // 360) + 1)
    all_danmaku = []

    for seg_idx in range(1, total_segments + 1):
        try:
            buf = fetch_danmaku_segment(cid, seg_idx)
            danmaku = decode_danmaku_proto(buf)
            all_danmaku.extend(danmaku)
        except Exception as e:
            print(f"  [弹幕] 分段{seg_idx}下载失败: {e}")
            continue

    return all_danmaku


# ============================================================
# 五层检测算法
# ============================================================

def detect_from_chapters(view_points: list) -> Optional[dict]:
    """第1层: 视频章节标记 (最高置信度)"""
    if not view_points:
        return None
    for chapter in view_points:
        label = (chapter.get("content") or "").lower()
        if any(kw in label for kw in AD_CHAPTER_KEYWORDS):
            return {
                "start": chapter.get("from", 0),
                "end": chapter.get("to", 0),
                "source": "chapter",
                "label": chapter.get("content"),
            }
    return None


def detect_from_description(desc: str, duration: int) -> Optional[dict]:
    """第2层: 视频简介时间戳"""
    if not desc:
        return None

    entries = []
    for m in re.finditer(r'(?:^|\n)\s*(\d{1,2}):(\d{2})\s+(.+)', desc):
        entries.append({
            "time": int(m.group(1)) * 60 + int(m.group(2)),
            "label": m.group(3).strip().lower(),
        })

    if len(entries) < 2:
        return None

    for entry in entries:
        if any(kw in entry["label"] for kw in AD_CHAPTER_KEYWORDS):
            return {
                "start": entry["time"],
                "end": min(entry["time"] + 90, duration),
                "source": "description",
                "label": entry["label"],
            }
    return None


def detect_from_subtitles(subtitle_lines: list) -> Optional[dict]:
    """第3层: 字幕内容关键词聚类"""
    if not subtitle_lines or len(subtitle_lines) < 5:
        return None

    hits = []
    for line in subtitle_lines:
        text = (line.get("content") or "").lower()
        matched = [kw for kw in AD_CONTENT_KEYWORDS if kw in text]
        if matched:
            hits.append({
                "from": line.get("from", 0),
                "to": line.get("to", 0),
                "matched": matched,
            })

    if len(hits) < 2:
        return None

    # 找最密集的 120s 窗口
    MAX_AD_WINDOW = 120
    best_count = 0
    best_cluster = None

    for i in range(len(hits)):
        window_end = hits[i]["from"] + MAX_AD_WINDOW
        cluster = [h for h in hits if hits[i]["from"] <= h["from"] <= window_end]
        if len(cluster) > best_count:
            best_count = len(cluster)
            best_cluster = cluster

    if best_cluster and best_count >= 3:
        return {
            "start": best_cluster[0]["from"],
            "end": best_cluster[-1]["to"],
            "source": "subtitle",
            "hit_count": best_count,
            "matched_keywords": list(set(
                kw for h in best_cluster for kw in h["matched"]
            )),
        }
    return None


# ============================================================
# 弹幕时间解析 — 中文时间码识别
# ============================================================

def zh_num_to_int(s: str) -> int:
    """中文数字 → 整数: 五 → 5, 十 → 10, 三十五 → 35"""
    if re.match(r'^\d+$', s):
        return int(s)
    if s == '十':
        return 10
    if '十' in s:
        left, right = s.split('十', 1)
        return (ZH_NUM_MAP.get(left, 0) or 1) * 10 + (ZH_NUM_MAP.get(right, 0) or 0)
    return ZH_NUM_MAP.get(s, 0)


def extract_time_from_text(text: str) -> Optional[dict]:
    """
    从弹幕文本中提取时间码
    
    支持格式:
      - 数字: "5:30", "10:45"
      - 中文: "五分三十秒", "十分钟"
      - 混合: "5分30秒", "10.5分钟"
      - 编码: "705工程", "0705工程"
    """
    # 数字时间码: 5:30, 10:45
    m = re.search(r'(\d{1,2}):(\d{2})', text)
    if m:
        return {"time": int(m.group(1)) * 60 + int(m.group(2)), "format": "numeric"}

    # 混合格式: 5分30秒
    m = re.search(r'(\d+)\s*分\s*(\d+)\s*秒', text)
    if m:
        return {"time": int(m.group(1)) * 60 + int(m.group(2)), "format": "mixed"}

    # 中文数字: 五分三十秒
    m = re.search(r'([一二三四五六七八九十]+)分([一二三四五六七八九十]+)秒', text)
    if m:
        return {"time": zh_num_to_int(m.group(1)) * 60 + zh_num_to_int(m.group(2)), "format": "zh_num"}

    # 编码格式: 705工程, 0705工程
    m = re.search(r'(?:^|\D)(\d{3,4})(?:工程|空降)', text)
    if m:
        code = m.group(1)
        if len(code) == 4:
            mins, secs = int(code[:2]), int(code[2:])
        else:
            mins, secs = int(code[0]), int(code[1:])
        if 0 <= mins < 60 and 0 <= secs < 60:
            return {"time": mins * 60 + secs, "format": "encoded"}

    return None


def find_ad_timestamps(danmaku: list) -> Optional[dict]:
    """
    第4层: 弹幕时间码聚合
    
    弹幕中出现大量时间码 → 可能是广告段的起止标记
    """
    if not danmaku:
        return None

    timestamps = []
    for d in danmaku:
        extracted = extract_time_from_text(d.get("text", ""))
        if extracted:
            timestamps.append(extracted["time"])

    if len(timestamps) < 5:
        return None

    # 找最密集的60s窗口
    timestamps.sort()
    best_count = 0
    best_start = None

    for i in range(len(timestamps)):
        window_end = timestamps[i] + 60
        count = sum(1 for t in timestamps if timestamps[i] <= t <= window_end)
        if count > best_count:
            best_count = count
            best_start = timestamps[i]

    if best_count >= 4 and best_start:
        return {
            "start": max(0, best_start - 5),
            "end": best_start + 120,
            "source": "danmaku_time",
            "signal_count": best_count,
        }
    return None


def get_ad_time_by_keywords(danmaku: list) -> Optional[dict]:
    """
    第5层: 弹幕关键词方向性匹配
    
    开始词 ("广告来了") + 结束词 ("欢迎回来") → 双向锚定广告段
    """
    if not danmaku:
        return None

    CLUSTER_WINDOW = 15  # 聚类窗口(秒)
    MIN_CLUSTER = 2

    start_signals = []
    end_signals = []
    general_signals = []

    for d in danmaku:
        text = d.get("text", "").strip()
        t = d.get("time", 0)
        for kw in AD_START_KEYWORDS:
            if kw in text:
                start_signals.append(t)
                break
        for kw in AD_END_KEYWORDS:
            if kw in text:
                end_signals.append(t)
                break
        for kw in AD_GENERAL_KEYWORDS:
            if kw in text:
                general_signals.append(t)
                break

    # 聚类开始信号 → 广告起点
    start_cluster = _find_cluster(start_signals, CLUSTER_WINDOW, MIN_CLUSTER)
    end_cluster = _find_cluster(end_signals, CLUSTER_WINDOW, MIN_CLUSTER)

    if start_cluster and end_cluster and start_cluster < end_cluster:
        return {
            "start": start_cluster,
            "end": end_cluster,
            "source": "danmaku_keyword",
        }

    # 只有 general 信号 → 找 30-100s 的密集段
    if general_signals:
        result = _get_ad_by_general_keywords(general_signals)
        if result:
            return {
                "start": result["start"],
                "end": result["end"],
                "source": "danmaku_keyword_general",
            }

    return None


def _find_cluster(times: list, window_sec: int, min_size: int) -> Optional[float]:
    """在时间数组中找最小窗口内的密集聚类中心"""
    if len(times) < min_size:
        return None
    times.sort()
    for i in range(len(times) - min_size + 1):
        if times[i + min_size - 1] - times[i] <= window_sec:
            return times[i]  # 聚类起点
    return None


def _get_ad_by_general_keywords(times: list) -> Optional[dict]:
    """从 general 关键词信号中找 30-100s 的广告段"""
    if len(times) < 2:
        return None
    times.sort()
    AD_MAX = 100
    AD_MIN = 30

    i, j = 0, 1
    while i < len(times) and j < len(times):
        start, end = times[i], times[j]
        diff = end - start
        if diff > AD_MAX:
            if j - 1 == i:
                j += 1
            i += 1
        else:
            if diff >= AD_MIN:
                return {"start": start - 5, "end": end}
            j += 1
    return None


# ============================================================
# 综合采集入口
# ============================================================

@dataclass
class BiliSignals:
    """所有 B站原生信号的汇总"""
    bvid: str
    cid: int
    duration: int
    desc: str = ""
    view_points: list = field(default_factory=list)
    subtitles: list = field(default_factory=list)
    subtitle_body: list = field(default_factory=list)
    danmaku: list = field(default_factory=list)
    # 检测结果
    ad_from_chapter: Optional[dict] = None
    ad_from_description: Optional[dict] = None
    ad_from_subtitle: Optional[dict] = None
    ad_from_danmaku_time: Optional[dict] = None
    ad_from_danmaku_kw: Optional[dict] = None


def collect_all(bvid: str, cid: int, duration: int) -> BiliSignals:
    """采集所有 B站原生信号"""
    signals = BiliSignals(bvid=bvid, cid=cid, duration=duration)

    print("[信号] 正在采集 B站原生数据...")

    # 1. 视频信息 (简介)
    print("  1/5 视频简介...")
    try:
        info = fetch_video_info(bvid)
        signals.desc = info.get("desc", "")
        signals.duration = info.get("duration", duration)
    except Exception as e:
        print(f"    简介获取失败: {e}")

    # 2. 播放器信息 (章节 + 字幕列表)
    print("  2/5 章节+字幕列表...")
    try:
        player = fetch_player_info(bvid, cid)
        signals.view_points = player.get("view_points", []) or []
        signals.subtitles = (
            player.get("subtitle", {}).get("subtitles", []) or []
        )
        print(f"    章节: {len(signals.view_points)}个, 字幕: {len(signals.subtitles)}个")
    except Exception as e:
        print(f"    播放器信息获取失败: {e}")

    # 3. 字幕内容
    print("  3/5 字幕内容...")
    if signals.subtitles:
        try:
            zh_sub = next(
                (s for s in signals.subtitles if s.get("lan") in ("zh-CN", "ai-zh")),
                signals.subtitles[0],
            )
            url = zh_sub.get("subtitle_url", "")
            if url:
                signals.subtitle_body = fetch_subtitle_body(url)
                print(f"    字幕: {len(signals.subtitle_body)}行")
        except Exception as e:
            print(f"    字幕下载失败: {e}")
    else:
        print("    无官方字幕")

    # 4. 弹幕
    print("  4/5 弹幕...")
    try:
        signals.danmaku = fetch_all_danmaku(cid, signals.duration)
        print(f"    弹幕: {len(signals.danmaku)}条")
    except Exception as e:
        print(f"    弹幕获取失败: {e}")

    # 5. 五层检测
    print("  5/5 五层广告检测...")
    signals.ad_from_chapter = detect_from_chapters(signals.view_points)
    signals.ad_from_description = detect_from_description(
        signals.desc, signals.duration
    )
    signals.ad_from_subtitle = detect_from_subtitles(signals.subtitle_body)
    signals.ad_from_danmaku_time = find_ad_timestamps(signals.danmaku)
    signals.ad_from_danmaku_kw = get_ad_time_by_keywords(signals.danmaku)

    # 汇总
    hits = [
        ("章节", signals.ad_from_chapter),
        ("简介", signals.ad_from_description),
        ("字幕", signals.ad_from_subtitle),
        ("弹幕时间码", signals.ad_from_danmaku_time),
        ("弹幕关键词", signals.ad_from_danmaku_kw),
    ]
    for name, result in hits:
        if result:
            print(f"    ✅ {name}: {result['start']}s → {result['end']}s")
        else:
            print(f"    ❌ {name}: 未命中")

    return signals


def get_best_ad_segment(signals: BiliSignals) -> Optional[dict]:
    """
    从五层检测中取置信度最高的广告段
    
    优先级: 章节 > 简介 > 字幕 > 弹幕时间码 > 弹幕关键词
    """
    for result in [
        signals.ad_from_chapter,
        signals.ad_from_description,
        signals.ad_from_subtitle,
        signals.ad_from_danmaku_time,
        signals.ad_from_danmaku_kw,
    ]:
        if result:
            return result
    return None


if __name__ == "__main__":
    import sys
    bvid = sys.argv[1] if len(sys.argv) > 1 else "BV1GJ411X7h7"
    cid = int(sys.argv[2]) if len(sys.argv) > 2 else 131844501
    dur = int(sys.argv[3]) if len(sys.argv) > 3 else 87

    signals = collect_all(bvid, cid, dur)

    best = get_best_ad_segment(signals)
    if best:
        print(f"\n🎯 最佳广告段: {best['start']}s → {best['end']}s (来源: {best.get('source')})")
    else:
        print("\n🎯 未检测到广告段")
