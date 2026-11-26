"""启动工作台：先探测同端口是否已有本服务，避免开两份数据库写连接。"""

import argparse
import json
import threading
import time
import urllib.error
import urllib.request
import webbrowser

from app import config
from app.api.http import serve


def probe(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.6) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def free_port(host, start, limit=10):
    for port in range(start, start + limit):
        if probe(port) is None:
            return port
    return None


def main():
    parser = argparse.ArgumentParser(description="评香工作台")
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}/"
    existing = probe(args.port)
    if existing and existing.get("service") == config.SERVICE:
        if existing.get("version") == config.VERSION:
            print(f"已在运行：{url}")
            if not args.no_browser:
                webbrowser.open(url)
            return
        print(f"端口 {args.port} 上还开着旧版本 {existing.get('version')}，换一个端口启动 {config.VERSION}。")
        print("确认不再需要旧窗口后，关掉它再用默认端口启动。")
        args.port = free_port(args.host, args.port + 1)
        if not args.port:
            print("附近端口都被占用，请先关掉旧窗口。")
            return
        url = f"http://{args.host}:{args.port}/"
    elif existing:
        print(f"端口 {args.port} 已被别的服务占用，请换端口：python -X utf8 launch.py --port {args.port + 1}")
        return

    if not args.no_browser:
        threading.Thread(target=lambda: (time.sleep(0.8), webbrowser.open(url)), daemon=True).start()
    serve(port=args.port, host=args.host)


if __name__ == "__main__":
    main()
