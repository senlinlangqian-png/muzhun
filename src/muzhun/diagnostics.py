"""Local readiness checks. Never download models or send diagnostic data."""
from __future__ import annotations

import importlib.metadata
import importlib.util
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

from . import __version__

MODELS = ("tiny", "base", "small", "medium", "large-v3-turbo")
MODEL_REPOSITORIES = {name: f"Systran/faster-whisper-{name}" for name in MODELS}
MODEL_REPOSITORIES["large-v3-turbo"] = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
DEPENDENCIES = {
    "fastapi": "fastapi", "uvicorn": "uvicorn", "python-multipart": "multipart",
    "Pillow": "PIL", "numpy": "numpy", "imageio-ffmpeg": "imageio_ffmpeg",
    "av": "av", "rapidocr-onnxruntime": "rapidocr_onnxruntime",
    "faster-whisper": "faster_whisper", "pypinyin": "pypinyin", "opencc-python-reimplemented": "opencc",
}


def cached_models(cache: Path) -> list[str]:
    """Only call a snapshot cached when the required model files are present."""
    ready = []
    for name in MODELS:
        locations = [cache / name]
        repository = MODEL_REPOSITORIES[name].replace("/", "--")
        snapshots = cache / f"models--{repository}" / "snapshots"
        if snapshots.is_dir():
            locations.extend(snapshots.iterdir())
        if any(all((folder / file).is_file() and (folder / file).stat().st_size > 0
                   for file in ("model.bin", "config.json", "tokenizer.json"))
               for folder in locations):
            ready.append(name)
    return ready


def runtime_report(root: Path, full: bool = False) -> dict:
    checks = []
    versions = {}
    details = {"ffmpeg": None, "font": None, "ocr": None}

    def add(key, label, action, hint):
        try:
            message = action()
            checks.append({"id": key, "label": label, "ok": True, "message": str(message), "hint": ""})
        except Exception as error:
            checks.append({"id": key, "label": label, "ok": False, "message": str(error), "hint": hint})

    def python_check():
        if sys.version_info < (3, 10):
            raise RuntimeError("需要 Python 3.10 或更新版本，推荐 3.12")
        return f"Python {platform.python_version()} · {platform.machine()}"

    def dependencies_check():
        missing = []
        for distribution, module in DEPENDENCIES.items():
            try:
                if importlib.util.find_spec(module) is None:
                    missing.append(distribution)
                else:
                    versions[distribution] = importlib.metadata.version(distribution)
            except (ImportError, ValueError, importlib.metadata.PackageNotFoundError):
                missing.append(distribution)
        if missing:
            raise RuntimeError("缺少依赖：" + ", ".join(missing))
        return "处理依赖已安装"

    def ffmpeg_check():
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        run = subprocess.run([path, "-hide_banner", "-filters"], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=15)
        if run.returncode or not any(" ass " in line for line in run.stdout.splitlines()):
            raise RuntimeError("FFmpeg 无法运行，或缺少 ASS 字幕合成滤镜")
        details["ffmpeg"] = path
        return "视频合成可用"

    def font_check():
        from .layout import font_path
        path, family = font_path()
        from PIL import ImageFont
        ImageFont.truetype(path, 24)
        details["font"] = path
        return family

    def output_check():
        directory = root / "outputs"
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=directory) as file:
            file.write(b"muzhun")
        return "结果目录可写"

    add("python", "Python", python_check, "安装 Python 3.12 后重新启动。")
    add("dependencies", "处理依赖", dependencies_check, "重新运行启动器安装依赖。")
    add("ffmpeg", "视频导出", ffmpeg_check, "重新安装 imageio-ffmpeg，或用 IMAGEIO_FFMPEG_EXE 指定可用的 FFmpeg。")
    add("font", "中文字幕字体", font_check, "安装 Noto Sans CJK，或用 MUZHUN_FONT 指定中文字体文件。")
    add("output", "保存结果", output_check, "将项目解压到可写目录，再启动。")
    if full:
        def ocr_check():
            from .media import ocr_engine
            details["ocr"] = bool(ocr_engine())
            if not details["ocr"]:
                raise RuntimeError("OCR 初始化失败")
            # Importing also checks that the speech engine's native libraries load.
            from faster_whisper import WhisperModel  # noqa: F401
            return "画面识别和语音引擎已加载；没有下载语音模型"
        add("ocr", "识别引擎", ocr_check, "重新安装依赖，并检查错误信息；Windows 需使用 64 位 Python。")
    models = cached_models(root / ".cache" / "models")
    return {"version": __version__, "python": sys.executable, "root": str(root),
            **details, "versions": versions, "model_cache": str(root / ".cache" / "models"),
            "models_cached": models, "ready": all(item["ok"] for item in checks),
            "checks": checks, "full": full,
            "model_note": "演示或已有 SRT 无需语音模型；自动转录首次需要联网下载所选模型。"}
