from __future__ import annotations

import json
import hashlib
import copy
import math
import os
import secrets
import shutil
import subprocess
import time
from functools import lru_cache
from pathlib import Path

import av
from PIL import Image

from .subtitles import ass_escape, timestamp

from .limits import MAX_DURATION


def probe(path: Path) -> dict:
    with av.open(str(path)) as container:
        if not container.streams.video:
            raise ValueError("请上传含画面的 MP4、MOV、MKV 或 WebM 视频")
        stream = container.streams.video[0]
        duration = float(container.duration / av.time_base) if container.duration else float((stream.duration or 0) * stream.time_base)
        if not math.isfinite(duration) or duration <= 0 or duration > MAX_DURATION:
            raise ValueError("支持时长不超过 2 小时的可解码视频")
        return {"width": stream.width, "height": stream.height, "duration": round(duration, 3),
                "fps": float(stream.average_rate or 25), "has_audio": bool(container.streams.audio), "filename": path.name}


def extract_frames(video: Path, job_dir: Path, metadata: dict, progress) -> list[dict]:
    frame_dir = job_dir / "frames"
    frame_dir.mkdir(exist_ok=True)
    step = max(1.0, metadata["duration"] / 600)
    times = [round(index * step, 3) for index in range(int(metadata["duration"] / step) + 1)]
    times = [t for t in times if t < metadata["duration"] - 0.04]
    result = []
    with av.open(str(video)) as container:
        stream = container.streams.video[0]
        offset = float((stream.start_time or 0) * stream.time_base)
        for index, target in enumerate(times):
            container.seek(round((target + offset) / stream.time_base), stream=stream, backward=True)
            for frame in container.decode(stream):
                actual = float(frame.time or 0) - offset
                # Accept a frame at or after the requested time. A one-frame
                # look-back can otherwise select the previous shot at a cut.
                if actual + 1e-6 < target:
                    continue
                image = frame.to_image().convert("RGB")
                if image.width > 960:
                    image = image.resize((960, round(image.height * 960 / image.width)), Image.Resampling.LANCZOS)
                filename = f"frames/{index:04d}.jpg"
                image.save(job_dir / filename, quality=90)
                result.append({"time": round(max(0.0, actual), 3), "image": filename,
                               "width": image.width, "height": image.height, "ocr": []})
                break
            progress(0.06 + 0.12 * (index + 1) / len(times), f"提取画面 {index + 1}/{len(times)}")
    if not result:
        raise ValueError("视频画面无法解码")
    return result


@lru_cache(maxsize=1)
def ocr_engine():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)


def recognize_frames(frames: list[dict], job_dir: Path, progress) -> None:
    engine = ocr_engine()
    observed = {}
    for index, frame in enumerate(frames):
        signature = hashlib.sha256((job_dir / frame["image"]).read_bytes()).hexdigest()
        if signature in observed:
            frame["ocr"] = copy.deepcopy(observed[signature])
            frame["ocr_reused"] = True
            progress(.18 + .35 * (index + 1) / len(frames), f"复用相同画面 {index + 1}/{len(frames)}")
            continue
        result, _ = engine(str(job_dir / frame["image"]))
        items = []
        for box, text, confidence in result or []:
            xs, ys = [float(p[0]) for p in box], [float(p[1]) for p in box]
            items.append({"text": text, "confidence": round(float(confidence), 4),
                          "rect": [max(0, min(xs) / frame["width"]), max(0, min(ys) / frame["height"]),
                                   min(1, max(xs) / frame["width"]), min(1, max(ys) / frame["height"])]})
        frame["ocr"] = items
        observed[signature] = items
        progress(0.18 + 0.35 * (index + 1) / len(frames), f"识别画面文字 {index + 1}/{len(frames)}")


@lru_cache(maxsize=2)
def whisper_model(name: str, cache: str):
    from faster_whisper import WhisperModel
    if name not in {"tiny", "base", "small", "medium", "large-v3-turbo"}:
        raise ValueError("不支持的语音模型")
    return WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=min(8, os.cpu_count() or 4),
                        download_root=cache)


def transcribe(video: Path, metadata: dict, model: str, cache_dir: Path, progress, audio_path: Path,
               hints: list[str] | None = None, language: str | None = None, content="speech") -> tuple[list[dict], dict]:
    if not metadata["has_audio"]:
        raise ValueError("视频没有音轨。请同时提供 SRT 字幕。")
    from .transcription import decode_audio, recognize, speech_cues
    progress(0.54, "解码音轨")
    duration = decode_audio(video, audio_path)
    def recognition_progress(value, message):
        progress(.56 + .25 * value, message)
    words, segments, info = recognize(audio_path, model, cache_dir, recognition_progress,
        language=language, hints=hints, engine_factory=whisper_model,
        singing=content == "mixed", recover_gaps=content == "mixed")
    cues = speech_cues(words, segments, min(metadata["duration"], duration))
    if not cues:
        raise ValueError("没有识别到可用语音，请检查音轨或上传已有 SRT")
    return cues, info


def write_ass(placements: list[dict], width: int, height: int) -> str:
    header = f"""[Script Info]
Title: Muzhun
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Clean,Microsoft YaHei,30,&H00FFFFFF,&H00FFFFFF,&H000C0C0C,&H80000000,0,0,0,0,100,100,0,0,1,2,0,5,0,0,0,1
Style: Plate,Microsoft YaHei,30,&H00FFFFFF,&H00FFFFFF,&H90000000,&H90000000,0,0,0,0,100,100,0,0,3,5,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for cue in placements:
        style = "Plate" if cue["background"] else "Clean"
        bold = 1 if cue["font"] == "bold" else 0
        # The opaque plate uses border width as padding. Clean captions use
        # the requested text outline, matching the selected preview preset.
        border = 5 if cue["background"] else cue["outline"]
        tags = "{" + f"\\an5\\pos({cue['x']},{cue['y']})\\fn{cue['font_family']}\\fs{cue['font_size']}\\b{bold}\\bord{border}\\q2" + "}"
        lines.append(f"Dialogue: 0,{timestamp(cue['start'], True)},{timestamp(cue['end'], True)},{style},,0,0,0,,{tags}{ass_escape(cue['text'])}")
    return header + "\n".join(lines) + "\n"


def burn_video(video: Path, ass_file: Path, output: Path, progress) -> None:
    import imageio_ffmpeg
    filter_text = f"ass={ass_file.name}"
    from .layout import font_path
    chosen_font = Path(font_path()[0]).resolve()
    cached_font = Path(__file__).resolve().parents[2] / ".cache" / "fonts"
    # A font downloaded into the project is not registered with fontconfig.
    # Pass it to libass just as we do an explicit user font.
    if os.environ.get("MUZHUN_FONT") or chosen_font.is_relative_to(cached_font.resolve()):
        font_dir = ass_file.parent / "fonts"
        font_dir.mkdir(exist_ok=True)
        font_file = chosen_font
        destination = font_dir / ("custom" + font_file.suffix.lower())
        if destination.resolve() != font_file:
            shutil.copyfile(font_file, destination)
        filter_text += ":fontsdir=fonts"
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-i", str(video.resolve()),
               "-vf", filter_text, "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264",
               "-preset", "fast", "-crf", "20", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(output.resolve())]
    progress(0.1, "正在将字幕合成到视频")
    process = subprocess.run(command, cwd=ass_file.parent, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=max(900, MAX_DURATION * 2))
    if process.returncode != 0:
        raise RuntimeError("视频导出失败：" + process.stderr[-1800:])
    progress(1.0, "视频导出完成")


def _sharing_error(error: PermissionError) -> bool:
    return getattr(error, "winerror", None) in {5, 32, 33} or (os.name == "nt" and error.errno == 13)


def read_json(path: Path):
    delays = (.01, .025, .05, .1, .2)
    for attempt in range(len(delays) + 1):
        try:
            return json.loads(path.read_text("utf-8"))
        except PermissionError as error:
            if not _sharing_error(error) or attempt == len(delays):
                raise
            time.sleep(delays[attempt])


def write_json(path: Path, value) -> None:
    temporary = path.with_name(f"{path.name}.{secrets.token_hex(8)}.tmp")
    delays = (.01, .025, .05, .1, .2)
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")
        for attempt in range(len(delays) + 1):
            try:
                temporary.replace(path)
                break
            except PermissionError as error:
                # Windows readers and virus scanners can briefly deny rename.
                # Keep the complete old report until an atomic replace succeeds.
                if not _sharing_error(error) or attempt == len(delays):
                    raise
                time.sleep(delays[attempt])
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
