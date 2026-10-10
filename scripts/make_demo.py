"""Create an explicitly synthetic, controlled end-to-end demo; not a benchmark."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw

from muzhun.layout import get_font
from muzhun.media import probe, write_json
from muzhun.subtitles import write_srt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples"


def run(command):
    process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    if process.returncode:
        raise RuntimeError(process.stderr[-1500:])
    return process.stdout


def scene_image(index: int, term: str, title: str) -> Path:
    image = Image.new("RGB", (1280, 720), "#edf1e8")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1280, 62), fill="#243b2e")
    draw.text((35, 17), "MUZHUN  /  SYNTHETIC TUTORIAL", font=get_font("sans", 22), fill="#d5e8bd")
    draw.text((1170, 18), f"0{index+1}", font=get_font("sans", 22), fill="#aac291")
    draw.text((60, 98), title, font=get_font("bold", 38), fill="#355140")
    draw.rounded_rectangle((60, 169, 1218, 668), radius=18, fill="#ffffff", outline="#d3dfcc", width=2)
    draw.rectangle((62, 223, 1216, 226), fill="#e5ebdf")
    draw.text((87, 185), "training_config.py", font=get_font("sans", 21), fill="#7e9270")
    rows = [
        ['from peft import LoraConfig', 'config = LoraConfig(', '    target_modules = ["q_proj", "v_proj"],', ')', 'LoRA    rank = 8    alpha = 16'],
        ['import torch', 'device = torch.device("cuda")', 'tensor = tensor.to(device)', '# select the graphics processor', 'CUDA    device = "cuda:0"'],
        ['import torch', 'optimizer = torch.optim.AdamW(', '    model.parameters(),', ')', 'PyTorch    learning_rate = 0.001'],
    ][index]
    for row, text in enumerate(rows[:-1]):
        draw.text((97, 259 + row * 57), f"{row+1:02d}", font=get_font("sans", 24), fill="#bcc6b4")
        draw.text((157, 255 + row * 57), text, font=get_font("sans", 30), fill="#56765a")
    draw.rounded_rectangle((140, 556, 1155, 648), radius=12, fill="#e3efcf", outline="#94b575", width=2)
    draw.text((169, 575), rows[-1], font=get_font("bold", 37), fill="#244e32")
    draw.text((65, 687), "合成示例 · 画面与语音由脚本生成 · 输入错词为人为设置", font=get_font("sans", 14), fill="#89977f")
    path = OUT / f"scene-{index}.png"
    image.save(path)
    return path


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    scenes = [
        {"zh": "这一段讲 LoRA。这里把 LoRA 的 rank 设置为八，alpha 设置为十六。",
         "en": "This part explains LoRA. We set the LoRA rank to eight and the alpha value to sixteen."},
        {"zh": "这里选择 CUDA 设备。罗拉只是示例人名，不是当前的设备名称。",
         "en": "We select the CUDA device. Lola is an example person's name, not the name of this device."},
        {"zh": "这里使用 PyTorch。现在把 PyTorch 的学习率设置为零点零零一。",
         "en": "We use PyTorch here. Set the PyTorch learning rate to zero point zero zero one."},
    ]
    for index, scene in enumerate(scenes):
        scene["output"] = str((OUT / f"voice-{index}.wav").resolve())
    manifest = OUT / "speech-manifest.json"
    write_json(manifest, {"scenes": scenes})
    voice_name = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts" / "speak_demo.ps1"), "-Manifest", str(manifest)]).strip()
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    durations = []
    for index, (term, title) in enumerate([("LoRA", "01  参数与低秩微调"), ("CUDA", "02  选择计算设备"), ("PyTorch", "03  设置训练参数")]):
        import av
        with av.open(scenes[index]["output"]) as audio:
            duration = audio.duration / av.time_base + 0.7
        frame = scene_image(index, term, title)
        target = OUT / f"scene-{index}.mp4"
        run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-i", str(frame), "-i", scenes[index]["output"],
             "-t", str(duration), "-af", "apad=pad_dur=0.7", "-r", "25", "-c:v", "libx264", "-preset", "ultrafast",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", str(target)])
        durations.append(probe(target)["duration"])
    (OUT / "concat.txt").write_text("".join(f"file 'scene-{i}.mp4'\n" for i in range(3)), "utf-8")
    run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(OUT / "concat.txt"),
         "-c", "copy", "-movflags", "+faststart", str(OUT / "demo.mp4")])
    originals = [("这一段讲罗拉。", "这里把罗拉的 rank 设置为8，alpha 设置为16。"),
                 ("这里选择酷达设备。", "罗拉只是示例人名，不是当前的设备名称。"),
                 ("这里使用派托奇。", "现在把派托奇的学习率设置为0.001。")]
    truth = [("LoRA", "LoRA"), ("CUDA", "罗拉"), ("PyTorch", "PyTorch")]
    cues, labels = [], []
    cursor = 0.0
    for index, duration in enumerate(durations):
        cut = cursor + min(3.0, duration * .35)
        ends = [(cursor + .25, cut - .15), (cut + .1, cursor + duration - .35)]
        for part, (start, end) in enumerate(ends):
            cues.append({"start": round(start, 3), "end": round(end, 3), "text": originals[index][part]})
            labels.append({"start": round(start, 3), "end": round(end, 3), "terms": [truth[index][part]],
                          "regions": [[.1094, .7722, .9023, .9000]] if truth[index][part] != "罗拉" else []})
        cursor += duration
    (OUT / "demo-input.srt").write_text(write_srt(cues), "utf-8")
    write_json(OUT / "demo-truth.json", {"source": "synthetic-controlled-fixture", "items": labels})
    write_json(OUT / "demo-provenance.json", {"synthetic": True, "voice": voice_name, "scripts": ["make_demo.py", "speak_demo.ps1"],
                                             "controlled_errors": True, "purpose": "流程验证，不是独立识别评测", "duration": probe(OUT / "demo.mp4")["duration"]})
    print(json.dumps({"video": str(OUT / "demo.mp4"), "duration": cursor, "synthetic": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
