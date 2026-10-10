from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import av

from . import __version__
from .evidence import decision_for
from .media import burn_video, probe, write_json
from .pipeline import replan, save_exports


def template_page(name: str, data: dict) -> str:
    # JSON is data, including when a transcript contains HTML or </script>.
    payload = json.dumps(data, ensure_ascii=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    return (Path(__file__).parent / "web" / name).read_text("utf-8").replace("__MUZHUN_DATA__", payload)


def review_manifest(result: dict, mode: str) -> dict:
    cues = []
    for cue in result["cues"]:
        placements = [p for p in result["plans"][mode] if p["id"] == cue["id"]]
        if not placements:
            raise ValueError("处理记录缺少字幕布局，请重新排版")
        decisions = result.get("edits", {}).get(str(cue["id"]), {}).get("decisions", {})
        proposals = [{"from": p["from"], "to": p["to"], "decision": decision_for(p, i, decisions),
                      "reason": p["reason"], "evidence": [{"time": e["time"], "text": e["screen_text"]} for e in p["evidence"]]}
                     for i, p in enumerate(cue["proposals"])]
        segments = [{"start": p["start"], "end": p["end"], "position": p["label"],
                     "reason": p.get("movement_reason", "整句保持"), "layout_review": p["needs_review"],
                     "protected_labels": p.get("protected_labels", [])} for p in placements]
        cues.append({"id": cue["id"], "start": cue["start"], "end": cue["end"],
                     "original": cue["original"], "text": cue["original"] if mode == "A" else
                     cue.get("independent_text", cue["text"]) if mode == "B" else cue["text"],
                     "proposals": proposals if mode == "C" else [], "pending": cue["pending"] if mode == "C" else 0,
                     "layout_review": any(p["needs_review"] for p in placements),
                     "position": " → ".join(p["label"] for p in placements), "segments": segments,
                     "human_reviewed": bool(cue.get("reviewed")) if mode == "C" else False,
                     "bound_terms": sorted({b["term"] for b in cue["bindings"]}),
                     "manual_edit": bool(result.get("edits", {}).get(str(cue["id"])))})
    asr = result.get("asr", {})
    return {"version": __version__, "revision": result.get("revision", 0),
            "status": "draft-needs-listening-review", "mode": mode,
            "provenance": "synthetic-demo" if result.get("demo") else "user-supplied-unverified",
            "profile": result["profile"]["label"], "profile_method": result["profile"]["source"],
            "transcription": {"engine": asr.get("engine", "unspecified"), "model": asr.get("model"),
                              "screen_hotwords": asr.get("screen_hotwords", [])},
            "metadata": {key: result["metadata"][key] for key in ("width", "height", "duration")},
            "position_policy": result["settings"].get("position_policy", "adaptive") if mode == "C" else "static",
            "sampling_note": "位置按抽样画面更新，变化可能滞后一个抽样间隔；请检查换位前后的画面。",
            "summary": {"cues": len(cues), "pending": sum(c["pending"] for c in cues),
                        "human_reviewed": sum(c["human_reviewed"] for c in cues),
                        "unreviewed": sum(not c["human_reviewed"] for c in cues),
                        "layout_review": sum(c["layout_review"] for c in cues),
                        "unbound_cues": sum(not c["bound_terms"] for c in cues),
                        "manual_edits": sum(c["manual_edit"] for c in cues),
                        "adaptive_cues": sum(len(c["segments"]) > 1 for c in cues),
                        "within_cue_changes": sum(len(c["segments"]) - 1 for c in cues)},
            "cues": cues, "files": {"video": "video.mp4", "ass": "subtitles.ass", "srt": "subtitles.srt", "review": "review.html"},
            "note": "待核对为零也不等于全文准确。请听音、检查数字及单位；无画面绑定不代表字幕有错。SRT 不保留位置。"}


def verify_render(source: dict, rendered: dict) -> dict:
    if (source["width"], source["height"]) != (rendered["width"], rendered["height"]):
        raise ValueError("导出画面尺寸与源视频不一致")
    if abs(source["duration"] - rendered["duration"]) > .2:
        raise ValueError("导出时长与源视频相差超过 0.2 秒，请检查素材")
    if source.get("has_audio") and not rendered.get("has_audio"):
        raise ValueError("导出缺少源视频音轨")
    return {"dimensions_match": True, "duration_delta_seconds": round(rendered["duration"] - source["duration"], 3),
            "has_audio": rendered.get("has_audio", False), "scope": "file-structure-only; visual-and-audio-review-required"}


def rendered_previews(video: Path, folder: Path, cues: list[dict]) -> list[dict]:
    if not cues:
        return []
    selected = []
    dynamic = next((c for c in cues if len(c.get("segments", [])) > 1), None)
    if dynamic:
        # Decode both sides of the first move, not just the whole cue midpoint.
        selected.extend({**dynamic, **segment, "segment_index": i + 1} for i, segment in enumerate(dynamic["segments"][:3]))
    for cue in [cues[0], max(cues, key=lambda c: len(c["text"])),
                next((c for c in cues if c["pending"] or c["layout_review"]), cues[0]), cues[-1]]:
        midpoint = (cue["start"] + cue["end"]) / 2
        matching = next(((i, s) for i, s in enumerate(cue.get("segments", [])) if s["start"] <= midpoint < s["end"]), None)
        # Give each actual image one actual position label. The whole-cue
        # sequence is not the position visible in a single decoded frame.
        selected.append({**cue, **matching[1], "segment_index": matching[0] + 1} if matching else cue)
    selected = list({(c["id"], c["start"], c["end"]): c for c in selected}.values())[:8]
    preview_dir = folder / "previews"
    preview_dir.mkdir(exist_ok=True)
    previews = []
    with av.open(str(video)) as container:
        stream = container.streams.video[0]
        offset = float((stream.start_time or 0) * stream.time_base)
        for index, cue in enumerate(selected):
            target = (cue["start"] + cue["end"]) / 2
            container.seek(round((target + offset) / stream.time_base), stream=stream, backward=True)
            for frame in container.decode(stream):
                actual = float(frame.time or 0) - offset
                if actual + .04 < target:
                    continue
                image = frame.to_image().convert("RGB")
                image.thumbnail((1280, 1280))
                name = f"previews/{index + 1:02d}.jpg"
                image.save(folder / name, quality=92)
                previews.append({"cue_id": cue["id"], "time": round(actual, 3), "image": name,
                                 "source": "decoded-rendered-video", "position": cue.get("position"),
                                 "segment_index": cue.get("segment_index")})
                break
    if len(previews) != len(selected):
        raise ValueError("无法从实际导出视频提取复核画面")
    return previews


def delivery_pack(result: dict, job_dir: Path, video: Path, mode: str = "C", progress=lambda *_: None, *, edition: int | None = None) -> dict:
    if mode not in {"A", "B", "C"}:
        raise ValueError("交付模式须为 A、B 或 C")
    result = replan(result)
    source = probe(video)
    if (source["width"], source["height"]) != (result["metadata"]["width"], result["metadata"]["height"]) or abs(source["duration"] - result["metadata"]["duration"]) > .2:
        raise ValueError("视频与处理记录不匹配，请使用原素材")
    save_exports(result, job_dir)
    if edition is not None and (type(edition) is not int or edition < 0):
        raise ValueError("导出修订编号无效")
    name = f"delivery-{mode}" + (f"-r{edition}" if edition is not None else "")
    folder = job_dir / name
    folder.mkdir(exist_ok=True)
    for suffix in ("ass", "srt"):
        shutil.copyfile(job_dir / f"subtitles-{mode}.{suffix}", folder / f"subtitles.{suffix}")
    target = folder / "video.mp4"
    burn_video(video, folder / "subtitles.ass", target, lambda value, message: progress(value * .85, message))
    manifest = review_manifest(result, mode)
    manifest["verification"] = verify_render(source, probe(target))
    manifest["previews"] = rendered_previews(target, folder, manifest["cues"])
    write_json(folder / "manifest.json", manifest)
    (folder / "review.html").write_text(template_page("delivery-review.html", manifest), "utf-8")
    output = job_dir / f"{name}.zip"
    files = ["video.mp4", "subtitles.ass", "subtitles.srt", "manifest.json", "review.html"] + [p["image"] for p in manifest["previews"]]
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            archive.write(folder / name, name)
    progress(1, "完整交付包已生成，请听音复核")
    return {"output": str(output.resolve()), "review": str((folder / "review.html").resolve()),
            "manifest": str((folder / "manifest.json").resolve()), "video": str(target.resolve()),
            "status": manifest["status"], "summary": manifest["summary"], "verification": manifest["verification"]}
