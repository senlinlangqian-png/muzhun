"""Actual OCR, fixed/adaptive comparison and MP4 checks on controlled panels."""
import argparse
import json
import sys
from pathlib import Path

from muzhun import __version__
from muzhun.delivery import delivery_pack, verify_render
from muzhun.evaluation import evaluate
from muzhun.layout import _candidates
from muzhun.media import burn_video, probe, write_json
from muzhun.pipeline import process, replan, save_exports
from muzhun.subtitles import parse_srt

ROOT = Path(__file__).resolve().parents[1]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "outputs" / "v03-dynamic")
    parser.add_argument("--reuse", action="store_true", help="Reuse real OCR observations, never replace them with truth rectangles")
    args = parser.parse_args()
    folder = args.out.resolve()
    video = ROOT / "examples" / "dynamic-demo.mp4"
    if args.reuse:
        result = replan(json.loads((folder / "result.json").read_text("utf-8")), {"position_policy": "adaptive"})
    else:
        result = process(video, folder, {"position_policy": "adaptive"}, (ROOT / "examples" / "dynamic-input.srt").read_text("utf-8"))
    result.update(source_video=str(video.resolve()), demo=True)
    save_exports(result, folder)
    labels = json.loads((ROOT / "examples" / "dynamic-truth.json").read_text("utf-8"))
    fixed = replan(result, {"position_policy": "static"})
    fixed_folder = folder / "fixed"
    fixed_folder.mkdir(exist_ok=True)
    save_exports(fixed, fixed_folder)
    burn_video(video, fixed_folder / "subtitles-C.ass", fixed_folder / "video-C.mp4", lambda *_: None)
    delivery = delivery_pack(result, folder, video)
    adaptive_score = evaluate(result, labels)["scores"]["C"]
    fixed_score = evaluate(fixed, labels)["scores"]["C"]
    # Also report an oracle lower bound for an unmoving caption using exactly
    # the same font/anchor/wrapping candidates. Truth is used only for evaluation.
    candidates = _candidates(result["cues"][0]["text"], result["metadata"]["width"], result["metadata"]["height"], result["settings"], "C")
    oracle = min((evaluate({"plans": {"C": [{**candidate, "start": .2, "end": 11.8}]}}, labels)["scores"]["C"] for candidate in candidates),
                 key=lambda score: score["blocked_seconds"])
    assert adaptive_score["blocked_seconds"] < fixed_score["blocked_seconds"], "Adaptive placement did not improve the specified controlled case"
    assert len(parse_srt((folder / "subtitles-C.srt").read_text("utf-8"))) == len(result["cues"])
    assert result["summary"]["within_cue_changes"] == 2
    segments = result["plans"]["C"]
    assert [(p["start"], p["end"]) for p in segments] == [(.2, 4), (4, 8), (8, 11.8)]
    manifest = json.loads(Path(delivery["manifest"]).read_text("utf-8"))
    assert {p["segment_index"] for p in manifest["previews"] if p["segment_index"]} >= {1, 2}
    assert len(manifest["previews"]) == 3
    assert [p["position"] for p in manifest["previews"]] == ["下方", "上方", "下方"]
    summary = {"version": __version__, "provenance": labels["provenance"], "transcription": "provided-srt with one intentionally wrong alias",
               "truth_source": "generator-defined panel rectangles, not engine OCR or layout", "ocr_frames": len(result["frames"]),
               "ocr_boxes": sum(len(f["ocr"]) for f in result["frames"]), "edited_cues": len(result.get("edits", {})),
               "adaptive_C": adaptive_score, "fixed_C": fixed_score, "best_fixed_candidate_using_truth": oracle,
               "changes": [{"start": p["start"], "end": p["end"], "position": p["label"]} for p in segments],
               "fixed_video_verification": verify_render(probe(video), probe(fixed_folder / "video-C.mp4")),
               "adaptive_video_verification": delivery["verification"],
               "limitation": "One controlled synthetic fixture. Does not establish real game accuracy, global novelty or saved editing time."}
    write_json(folder / "controlled-comparison.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
