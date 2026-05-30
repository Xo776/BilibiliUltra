"""快速端到端测试 — B站信号采集"""
from bilibili_signals import collect_all
from audio_extractor import parse_bv, get_video_info

bvid = parse_bv("BV1GJ411X7h7")
info = get_video_info(bvid)
sig = collect_all(bvid, info.cid, info.duration)

print(f"\n弹幕: {len(sig.danmaku)}条")
print(f"章节: {len(sig.view_points)}个")
print(f"字幕行: {len(sig.subtitle_body)}行")

print("\n五层广告检测:")
for layer, r in [
    ("章节", sig.ad_from_chapter),
    ("简介", sig.ad_from_description),
    ("字幕", sig.ad_from_subtitle),
    ("弹幕时间码", sig.ad_from_danmaku_time),
    ("弹幕关键词", sig.ad_from_danmaku_kw),
]:
    if r:
        print(f"  ✅ {layer}: {r['start']}s -> {r['end']}s (来源: {r.get('source')})")
    else:
        print(f"  ❌ {layer}: 未命中")
