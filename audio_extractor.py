"""
音频提取模块
从 B站视频中提取纯音频流 URL 及视频元数据
"""
import re
import json
import requests
from dataclasses import dataclass, field
from typing import Optional

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com",
}


@dataclass
class VideoInfo:
    """B站视频元数据"""
    bvid: str
    aid: int
    cid: int
    title: str
    duration: int       # 秒
    cover: str
    owner_name: str
    owner_uid: int


@dataclass
class AudioStream:
    """音频流信息"""
    url: str
    codec: str          # aac / mp4a
    bitrate: int        # kbps
    size: int           # bytes (约)
    duration: int       # 秒
    backup_urls: list = field(default_factory=list)


def parse_bv(url_or_id: str) -> str:
    """从各种格式中提取纯 BV 号"""
    # 已经是 BV 号
    if re.match(r'^BV[a-zA-Z0-9]{10}$', url_or_id):
        return url_or_id
    # 从 URL 中提取
    m = re.search(r'(BV[a-zA-Z0-9]{10})', url_or_id)
    if m:
        return m.group(1)
    # AV 号转 BV（调 B站 API）
    m = re.search(r'av(\d+)', url_or_id, re.I)
    if m:
        return _av2bv(int(m.group(1)))
    raise ValueError(f"无法从 '{url_or_id}' 中提取 BV 号")


def _av2bv(aid: int) -> str:
    """AV 号转 BV 号"""
    resp = requests.get(
        f"https://api.bilibili.com/x/web-interface/view?aid={aid}",
        headers=HEADERS
    )
    data = resp.json()
    if data["code"] != 0:
        raise RuntimeError(f"AV转BV失败: {data.get('message')}")
    return data["data"]["bvid"]


def get_video_info(bvid: str) -> VideoInfo:
    """获取视频基本信息"""
    resp = requests.get(
        f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
        headers=HEADERS
    )
    data = resp.json()
    if data["code"] != 0:
        raise RuntimeError(f"获取视频信息失败: {data.get('message')}")

    v = data["data"]
    return VideoInfo(
        bvid=v["bvid"],
        aid=v["aid"],
        cid=v["cid"],
        title=v["title"],
        duration=v["duration"],
        cover=v["pic"],
        owner_name=v["owner"]["name"],
        owner_uid=v["owner"]["mid"],
    )


def get_audio_stream(bvid: str, cid: int) -> AudioStream:
    """
    获取音频流 URL（DASH 格式）
    
    fnval=4048 请求 DASH + 杜比音频
    对于只有 FLV 的老视频，回退到 fnval=16
    """
    for fnval in [4048, 16, 0]:
        resp = requests.get(
            "https://api.bilibili.com/x/player/wbi/playurl",
            params={
                "bvid": bvid,
                "cid": cid,
                "fnval": fnval,
                "fnver": 0,
                "fourk": 1,
                "platform": "pc",
            },
            headers=HEADERS,
        )
        data = resp.json()
        if data["code"] != 0:
            continue

        play = data["data"]

        # 新版 DASH 流
        if "dash" in play and play["dash"]:
            dash = play["dash"]
            audio = dash.get("audio")
            if audio and len(audio) > 0:
                a = audio[0]
                return AudioStream(
                    url=a["base_url"],
                    backup_urls=a.get("backup_url", []),
                    codec="aac",
                    bitrate=a.get("bandwidth", 0) // 1000,
                    size=0,
                    duration=play.get("timelength", 0) // 1000,
                )

        # 老版 FLV 单文件（音视频合并，无法分离）
        if "durl" in play and play["durl"]:
            durl = play["durl"][0]
            return AudioStream(
                url=durl["url"],
                backup_urls=durl.get("backup_url", []),
                codec="aac",
                bitrate=0,
                size=durl.get("size", 0),
                duration=play.get("timelength", 0) // 1000,
            )

    raise RuntimeError("无法获取音频流: 可能需要登录或视频不支持")


def download_audio(stream: AudioStream, output_path: str) -> str:
    """下载音频流到本地文件"""
    url = stream.url
    # 尝试主 URL，失败则换备用
    for i, u in enumerate([url] + stream.backup_urls):
        try:
            resp = requests.get(u, headers=HEADERS, stream=True, timeout=60)
            if resp.status_code == 200:
                with open(output_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                print(f"音频已下载: {output_path} ({stream.duration}s)")
                return output_path
        except Exception as e:
            print(f"URL {i} 下载失败: {e}")
            continue

    raise RuntimeError("所有音频 URL 下载均失败")


# --- 快捷入口 ---
def extract(bv_input: str, output_dir: str = ".") -> dict:
    """
    一键提取: 输入 BV 号或视频 URL, 返回音频信息 + 下载
    
    Returns:
        dict with keys: video_info, audio_stream, audio_path
    """
    bvid = parse_bv(bv_input)
    info = get_video_info(bvid)
    print(f"视频: {info.title} ({info.duration}s) - {info.owner_name}")

    stream = get_audio_stream(bvid, info.cid)
    print(f"音频: {stream.codec} {stream.bitrate}kbps, DASH={'是' if 'm4s' in stream.url else '否(FLV单文件)'}")

    ext = "m4a" if "m4s" in stream.url else "flv"
    safe_title = re.sub(r'[\\/*?:"<>|]', '', info.title)[:40]
    path = f"{output_dir}/{info.bvid}_{safe_title}.{ext}"

    download_audio(stream, path)

    return {
        "video_info": info,
        "audio_stream": stream,
        "audio_path": path,
    }


if __name__ == "__main__":
    import sys
    bv = sys.argv[1] if len(sys.argv) > 1 else "BV1GJ411X7h7"
    result = extract(bv, output_dir="./output")
    print(f"\n完成! 文件: {result['audio_path']}")
