"""Run the actual OCR/ASR/renderer on the synthetic fixture; never a quality claim."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from muzhun.evaluation import blind_pack, evaluate
from muzhun.evidence import screen_evidence
from muzhun.media import burn_video, probe, transcribe, write_json
from muzhun.pipeline import process, replan, save_exports

ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--asr", action="store_true")
    parser.add_argument("--model", default="small", choices=["tiny", "base", "small", "medium", "large-v3-turbo"])
    parser.add_argument("--blind", action="store_true")
    args = parser.parse_args()
    video = ROOT / "examples" / "demo.mp4"
    target = ROOT / "outputs" / "integration"
    target.mkdir(parents=True, exist_ok=True)
    progress = lambda value, message: print(f"{value:.0%} {message}", flush=True)
    result = process(video, target, srt=(ROOT / "examples" / "demo-input.srt").read_text("utf-8"), progress=progress)
    result.update(source_video=str(video), demo=True)
    scores = evaluate(result, json.loads((ROOT / "examples" / "demo-truth.json").read_text("utf-8")))
    assert scores["scores"]["C"]["terms_correct"] == 6, "controlled known spellings / negative control failed"
    assert scores["scores"]["C"]["blocked_seconds"] == 0, "known demonstration region blocked"
    save_exports(result, target)
    write_json(target / "synthetic-regression.json", scores)
    burn_video(video, target / "subtitles-C.ass", target / "video-C.mp4", progress)
    assert abs(probe(target / "video-C.mp4")["duration"] - probe(video)["duration"]) < .2
    if args.asr:
        hints = list(dict.fromkeys(term["text"] for term in result["terms"]
                                  if screen_evidence(term["text"], result["frames"])))[:24]
        cues, source = transcribe(video, result["metadata"], args.model, ROOT / ".cache", progress, target / "asr-audio.wav", hints)
        assert cues and all(c["start"] < c["end"] for c in cues)
        transcription = replan({**result, "cues": cues, "edits": {}})
        transcription["asr"] = source
        asr_target = ROOT / "outputs" / "integration-asr"
        asr_target.mkdir(exist_ok=True)
        shutil.copytree(target / "frames", asr_target / "frames", dirs_exist_ok=True)
        save_exports(transcription, asr_target)
        burn_video(video, asr_target / "subtitles-C.ass", asr_target / "video-C.mp4", progress)
        print(json.dumps({"actual_asr": source, "cues": len(cues),
                          "transcript": [c["original"] for c in cues]}, ensure_ascii=False))
    if args.blind:
        output = blind_pack(result, target, video, progress)
        import zipfile
        with zipfile.ZipFile(output) as archive:
            assert len([name for name in archive.namelist() if name.endswith(".mp4")]) == 3
            assert "blind-key.json" not in archive.namelist()
    print(json.dumps({"passed": True, "synthetic": True, "independent_quality_evaluation": False,
                      "report": str(target / "result.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
