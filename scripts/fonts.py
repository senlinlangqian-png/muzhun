"""Install a verified OFL-licensed CJK font only when no usable font exists."""
from __future__ import annotations

import hashlib
import os
import subprocess
import urllib.request
from pathlib import Path

FONT_URL = "https://raw.githubusercontent.com/notofonts/noto-cjk/f8d157532fbfaeda587e826d4cd5b21a49186f7c/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf"
FONT_SHA256 = "2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b"


def ensure_font(python: Path, root: Path):
    probe = subprocess.run([str(python), "-c", "from muzhun.layout import font_path; font_path()"],
                           cwd=root, capture_output=True)
    if probe.returncode == 0:
        return
    if os.environ.get("MUZHUN_FONT"):
        raise RuntimeError("MUZHUN_FONT 指定的字体不可用，请修正这个路径后重新安装")
    print("本机没有可用中文字体，正在下载 Noto Sans CJK（约 16 MB，OFL 许可）…", flush=True)
    folder = root / ".cache" / "fonts"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "NotoSansCJKsc-Regular.otf"
    request = urllib.request.Request(FONT_URL, headers={"User-Agent": "Muzhun-setup"})
    with urllib.request.urlopen(request, timeout=60) as response:
        content = response.read(25 * 1024 * 1024)
    if hashlib.sha256(content).hexdigest() != FONT_SHA256:
        raise RuntimeError("字体文件校验失败，请检查网络后重新安装")
    temporary = target.with_suffix(".download")
    temporary.write_bytes(content)
    temporary.replace(target)
    check = subprocess.run([str(python), "-c", "from muzhun.layout import font_path; font_path()"], cwd=root, capture_output=True)
    if check.returncode:
        raise RuntimeError("字体下载后仍无法加载，请运行 doctor 查看具体问题")
