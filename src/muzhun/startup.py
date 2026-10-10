"""Bind a local port before serving, and open a browser only after readiness."""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
import webbrowser

from . import __version__


def bind_port(port: int, attempts: int = 20) -> socket.socket:
    if not 1 <= port <= 65535:
        raise ValueError("端口应在 1–65535 之间")
    for selected in range(port, min(port + attempts, 65536)):
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            connection.bind(("127.0.0.1", selected))
            connection.listen(128)
            return connection
        except OSError:
            connection.close()
    raise RuntimeError("本地端口均被占用，请用 --port 指定另一个端口")


def open_when_ready(url: str, timeout: float = 30):
    deadline = time.monotonic() + timeout
    # Do not route localhost health checks through system HTTP proxies.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        try:
            with opener.open(url + "/api/health", timeout=1) as response:
                state = json.load(response)
            if state.get("app") == "muzhun" and state.get("version") == __version__:
                webbrowser.open(url)
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.2)


def serve(app, port: int, open_browser: bool = False):
    import uvicorn
    with bind_port(port) as connection:
        selected = connection.getsockname()[1]
        url = f"http://127.0.0.1:{selected}"
        print(f"幕准 {__version__}：{url}\n关闭此窗口或按 Ctrl+C 可停止服务。", flush=True)
        if selected != port:
            print(f"端口 {port} 已被占用，已使用 {selected}。", flush=True)
        if open_browser:
            threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
        uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[connection])
