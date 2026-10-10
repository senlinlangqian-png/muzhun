"""Generate known moving panels, spoken audio and separately specified truth.

This controlled fixture tests a changing layout, not real-user performance.
Windows SAPI supplies the narration; no game footage or fonts are distributed.
"""
from pathlib import Path
import json
import subprocess
import sys

import imageio_ffmpeg
from PIL import Image, ImageDraw

from muzhun.layout import get_font
from muzhun.media import write_json
from muzhun.subtitles import write_srt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples"
RECTS = [(32, 28, 1248, 520), (32, 200, 1248, 692)]


def run(args):
    completed = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    if completed.returncode:
        raise RuntimeError(completed.stderr[-2000:])
    return completed.stdout


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(exist_ok=True)
    for index, rect in enumerate(RECTS):
        image = Image.new("RGB", (1280, 720), "#dce7d5")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(rect, radius=18, fill="#ffffff", outline="#6b8961", width=3)
        draw.text((58, rect[1] + 20), "LoRA  /  PARAMETER PANEL  /  CONTROLLED DEMO", font=get_font("bold", 32), fill="#305238")
        values = ["rank = 8", "alpha = 16", "dropout = 0.05", "bias = NONE", "task = TRAINING", "layers = 32"]
        for row, value in enumerate(values):
            text = "LoRA    " + value + "    |    TARGET_MODULES = q_proj, v_proj"
            draw.text((58, rect[1] + 91 + row * 63), text, font=get_font("sans", 29), fill="#32513b")
        image.save(OUT / f"dynamic-panel-{index}.png")
    speech = OUT / "dynamic-speech.json"
    write_json(speech, {"scenes": [{"zh": "这里的 LoRA 参数面板中途换位，字幕也要避开正在讲的区域。",
                                   "en": "The LoRA parameter panel changes position. The caption should avoid the panel.",
                                   "output": str((OUT / "dynamic-voice.wav").resolve())}]})
    voice = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts" / "speak_demo.ps1"), "-Manifest", str(speech)]).strip()
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    for index in range(2):
        run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-i", str(OUT / f"dynamic-panel-{index}.png"),
             "-t", "4", "-r", "25", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(OUT / f"dynamic-{index}.mp4")])
    (OUT / "dynamic-concat.txt").write_text("file 'dynamic-0.mp4'\nfile 'dynamic-1.mp4'\nfile 'dynamic-0.mp4'\n", "utf-8")
    run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(OUT / "dynamic-concat.txt"),
         "-i", str(OUT / "dynamic-voice.wav"), "-t", "12", "-af", "apad", "-c:v", "copy", "-c:a", "aac", "-movflags", "+faststart", str(OUT / "dynamic-demo.mp4")])
    (OUT / "dynamic-input.srt").write_text(write_srt([{"start": .2, "end": 11.8, "text": "这里的罗拉参数面板中途换位，字幕也要避开正在讲的区域。"}]), "utf-8")
    write_json(OUT / "dynamic-truth.json", {"provenance": "synthetic-controlled-moving-panels", "items": [
        {"start": start, "end": end, "terms": ["LoRA"], "regions": [[rect[0]/1280, rect[1]/720, rect[2]/1280, rect[3]/720]]}
        for start, end, rect in [(.2, 4, RECTS[0]), (4, 8, RECTS[1]), (8, 11.8, RECTS[0])]]})
    write_json(OUT / "dynamic-provenance.json", {"synthetic": True, "voice": voice, "controlled_errors": True,
                                               "purpose": "变化布局的实际 OCR 与渲染验证，不是独立真实视频评测",
                                               "truth_source": "generator-defined panel rectangles, not engine outputs", "changes": [4, 8]})
    print(json.dumps({"video": str(OUT / "dynamic-demo.mp4"), "synthetic": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
