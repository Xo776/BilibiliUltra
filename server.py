"""
本地 HTTP 服务器 — 桥接 Chrome 扩展与 Python 分析管道

启动:
  python server.py
  
扩展通过 http://localhost:8765/analyze?bvid=xxx 触发分析
"""
import json
import sys
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# 确保能 import 本项目的模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from audio_extractor import parse_bv, get_video_info, get_audio_stream, download_audio
from content_analyzer import run as analyze_run
from config import OUTPUT_DIR


class AnalysisHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/analyze":
            self._handle_analyze(parsed)
        elif parsed.path == "/health":
            self._send_json({"status": "ok"})
        else:
            self._send_json({"error": "not found"}, 404)

    def _handle_analyze(self, parsed):
        params = parse_qs(parsed.query)
        bvid = params.get("bvid", [None])[0]

        if not bvid:
            self._send_json({"error": "需要 bvid 参数"}, 400)
            return

        # 从请求头读取 API 配置 (扩展传入)
        groq_key = self.headers.get("X-Groq-Key", "")
        llm_provider = self.headers.get("X-LLM-Provider", "openai")
        llm_key = self.headers.get("X-LLM-Key", "")
        llm_base_url = self.headers.get("X-LLM-Base-Url", "")
        llm_model = self.headers.get("X-LLM-Model", "")

        # 设置为环境变量 (本次请求有效)
        if groq_key:
            os.environ["GROQ_API_KEY"] = groq_key
        if llm_key:
            os.environ["LLM_PROVIDER"] = llm_provider
            os.environ["OPENAI_API_KEY"] = llm_key
            if llm_base_url:
                os.environ["OPENAI_BASE_URL"] = llm_base_url
            if llm_model:
                os.environ["OPENAI_MODEL"] = llm_model

        try:
            bvid = parse_bv(bvid)
            info = get_video_info(bvid)
            print(f"\n[Server] 分析: {info.title} ({bvid})")

            # 尝试下载音频
            audio_path = None
            try:
                stream = get_audio_stream(bvid, info.cid)
                audio_path = os.path.join(OUTPUT_DIR, f"{bvid}.m4a")
                download_audio(stream, audio_path)
            except Exception as e:
                print(f"[Server] 音频下载失败(将用B站字幕): {e}")

            # 运行分析
            result = analyze_run(
                audio_path=audio_path,
                video_info=info,
                bvid=bvid,
                cid=info.cid,
            )

            self._send_json(result)

        except Exception as e:
            print(f"[Server] 错误: {e}")
            self._send_json({"error": str(e)}, 500)

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {args[0]}")


if __name__ == "__main__":
    port = 8765
    server = HTTPServer(("127.0.0.1", port), AnalysisHandler)
    print(f"""
╔══════════════════════════════════════╗
║   B站内容密度分析器 - 本地服务        ║
║   http://localhost:{port}              ║
║                                      ║
║   使用方法:                           ║
║   1. 设置环境变量 (API Keys)          ║
║   2. Chrome 加载 extension/ 目录      ║
║   3. 打开 B站视频 → 点插件图标 → 分析 ║
╚══════════════════════════════════════╝
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Server] 已停止")
        server.shutdown()
