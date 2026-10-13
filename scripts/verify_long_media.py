"""Opt-in actual ASR/render check on 11-minute original synthetic speech.

Not run by ordinary unit tests. Uses a cached model, or downloads it on first use.
The repeated 21-second source includes an utterance across a recognition seam.
"""
import argparse
import math
import json
import re
import subprocess
import time
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg

from muzhun import __version__
from muzhun.delivery import delivery_pack
from muzhun.layout import font_path
from muzhun.media import write_json
from muzhun.pipeline import process, save_exports
from muzhun.transcription import CHUNK_SECONDS, decode_audio

ROOT = Path(__file__).resolve().parents[1]


def word_errors(expected, actual):
    reference = re.findall(r"[a-z0-9']+", expected.casefold())
    hypothesis = re.findall(r"[a-z0-9']+", actual.casefold())
    previous = list(range(len(hypothesis) + 1))
    for i, word in enumerate(reference, 1):
        current = [i]
        for j, other in enumerate(hypothesis, 1):
            current.append(min(previous[j] + 1, current[-1] + 1, previous[j - 1] + (word != other)))
        previous = current
    return {"reference_words": len(reference), "hypothesis_words": len(hypothesis),
            "word_edits": previous[-1], "wer": round(previous[-1] / max(1, len(reference)), 4)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / ".cache/v1-validation/long-media")
    parser.add_argument("--model", default="base")
    parser.add_argument("--duration", type=int, default=662, choices=[662, 7200])
    parser.add_argument("--continuous", action="store_true", help="Repeat the original speech throughout the file")
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    normalized = out / "original-speech.wav"
    decode_audio(ROOT / "examples/lyrics-demo.wav", normalized)
    with wave.open(str(normalized), "rb") as source:
        speech, rate = source.readframes(source.getnframes()), source.getframerate()
    offsets = (0, 298, 640) if args.duration == 662 else (0, 3598, args.duration - 22)
    if args.continuous:
        speech_seconds = len(speech) / 2 / rate
        offsets = [round(index * speech_seconds, 6) for index in range(int(args.duration / speech_seconds))]
    audio = out / "long.wav"
    with wave.open(str(audio), "wb") as target:
        target.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        position = 0
        for start in offsets:
            start_frame = round(start * rate)
            target.writeframesraw(b"\0\0" * (start_frame - position))
            target.writeframesraw(speech)
            position = start_frame + len(speech) // 2
        target.writeframesraw(b"\0\0" * (args.duration * rate - position))
    image = Image.new("RGB", (960, 540), "#f7f9fc")
    draw = ImageDraw.Draw(image); font = ImageFont.truetype(font_path()[0], 28)
    draw.text((60, 70), "Muzhun / long video transcription", font=font, fill="#202124")
    draw.text((60, 130), f"Original synthetic speech / {args.duration} seconds", font=font, fill="#687078")
    caption = "Repeated speech throughout the file" if args.continuous else f"Speech at {offsets[0]}s, {offsets[1]}s and {offsets[2]}s"
    draw.text((60, 220), caption, font=font, fill="#2563eb")
    draw.text((60, 275), "No supplied SRT. Real ASR. Global timestamps.", font=font, fill="#202124")
    panel = out / "panel.png"; image.save(panel)
    video = out / "long.mp4"
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-loop", "1",
                    "-framerate", "1", "-i", str(panel), "-i", str(audio), "-t", str(args.duration), "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k", str(video)], check=True)
    started = time.monotonic()
    last_progress = -1
    def progress(value, message):
        nonlocal last_progress
        if int(value * 100) != last_progress or "段" in message or value >= .85:
            last_progress = int(value * 100)
            print(f"[{value:.2f}] {message}", flush=True)
    result = process(video, out / "processed", {"profile": "general", "language": "en"},
                     model=args.model, cache_dir=ROOT / ".cache", progress=progress)
    result.update(source_video=str(video), demo=True)
    save_exports(result, out / "processed")
    delivery = delivery_pack(result, out / "processed", video)
    expected = (ROOT / "examples/lyrics-demo.txt").read_text("utf-8") * len(offsets)
    actual = " ".join(c["original"] for c in result["cues"])
    summary = {"version": __version__, "provenance": "original-synthetic-speech-repeated" if args.continuous else "original-synthetic-speech-with-silence",
        "duration": result["metadata"]["duration"], "asr": result["asr"], "cues": len(result["cues"]),
        "last_start": result["cues"][-1]["start"], "ocr_frames": len(result["frames"]),
        "reused_ocr_frames": sum(bool(f.get("ocr_reused")) for f in result["frames"]),
        "seconds": round(time.monotonic() - started, 2), "controlled_word_error": word_errors(expected, actual),
        "render_verification": delivery["verification"],
        "limitation": "Synthetic English speech; not a real-world accuracy estimate or singing benchmark."}
    assert result["metadata"]["duration"] > 600
    assert result["cues"][-1]["start"] > offsets[-1]
    assert result["asr"]["chunks"] == math.ceil(args.duration / CHUNK_SECONDS)
    write_json(out / "validation.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
