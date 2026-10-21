from __future__ import annotations

import copy
import math
import time
from pathlib import Path

from . import __version__
from .editing import refresh_review
from .evidence import apply_corrections, bind_regions, decision_for, proposal_key, propose_corrections, screen_evidence, visible_terms
from .layout import STYLES, estimated_metrics, plan
from .media import extract_frames, probe, recognize_frames, transcribe, write_ass, write_json
from .profiles import PROFILES, detect_profile, load_terms
from .subtitles import parse_srt, write_srt
from .limits import LANGUAGES, MAX_VIDEO_BYTES


def settings_check(settings: dict) -> dict:
    if settings.get("style", "professional") not in STYLES:
        raise ValueError("不支持的字幕样式")
    if settings.get("font", "sans") not in {"sans", "bold", "mono"}:
        raise ValueError("不支持的字体")
    if not 0.65 <= float(settings.get("font_scale", 1)) <= 1.6:
        raise ValueError("字号倍率须在 0.65 至 1.6 之间")
    settings["font_scale"] = float(settings.get("font_scale", 1))
    if settings.get("position_policy", "adaptive") not in {"adaptive", "static"}:
        raise ValueError("位置策略须为 adaptive 或 static")
    settings.setdefault("position_policy", "adaptive")
    if settings.get("language", "auto") not in LANGUAGES:
        raise ValueError("不支持的识别语言")
    if settings.get("audio_content", "speech") not in {"speech", "mixed"}:
        raise ValueError("音轨内容须为 speech 或 mixed")
    settings.setdefault("audio_content", "speech")
    if settings.get("script", "auto") not in {"auto", "original", "simplified"}:
        raise ValueError("不支持的中文字形")
    for region in settings.get("regions", []):
        rect = region.get("rect", [])
        if len(rect) != 4 or not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in rect) or rect[0] >= rect[2] or rect[1] >= rect[3]:
            raise ValueError("保护区域须为有效的归一化矩形")
        start, end = region.get("start", 0), region.get("end")
        if not isinstance(start, (int, float)) or not math.isfinite(start) or start < 0 or (
            end is not None and (not isinstance(end, (int, float)) or not math.isfinite(end) or end <= start)
        ):
            raise ValueError("保护区域的时间须有效，且结束晚于开始")
        if end is None:
            region.pop("end", None)
    for pin in settings.get("pins", {}).values():
        if len(pin) != 2 or not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in pin):
            raise ValueError("字幕位置须在画面范围内")
    return settings


def replan(result: dict, settings: dict | None = None, edits: dict | None = None) -> dict:
    output = copy.deepcopy(result)
    output.setdefault("initial_version", output.get("version", __version__))
    output["version"] = __version__
    output["settings"].update(settings or {})
    settings_check(output["settings"])
    if edits:
        output.setdefault("edits", {}).update(edits)
    profile_request = output["settings"].get("profile", "auto")
    content = " ".join(c["original"] for c in output["cues"]) + " " + " ".join(item["text"] for f in output["frames"] for item in f["ocr"])
    output["profile"] = detect_profile(content, profile_request)
    terms = load_terms(output["profile"]["id"], output["settings"].get("glossary", ""))
    known = {term["text"].lower() for term in terms}
    terms.extend(term for term in visible_terms(output["frames"]) if term["text"].lower() not in known)
    output["terms"] = terms
    for cue in output["cues"]:
        edit = output.get("edits", {}).get(str(cue["id"]), {})
        previous_proposals = cue.get("proposals")
        for key in ("start", "end"):
            cue.setdefault("source_" + key, cue[key])
            cue[key] = float(edit.get(key, cue["source_" + key]))
        if not all(math.isfinite(cue[key]) for key in ("start", "end")) or cue["start"] < 0 or cue["end"] <= cue["start"] or cue["end"] > output["metadata"]["duration"] + 0.1:
            raise ValueError("字幕时间须位于视频内且结束晚于开始")
        base_text = cue["original"]
        script = output["settings"].get("script", "auto")
        if output.get("asr", {}).get("engine") == "faster-whisper" and (script == "simplified" or (script == "auto" and output["asr"].get("language") == "zh")):
            from .lyrics import simplified
            base_text = simplified(base_text)
        analysis_cue = {**cue, "original": base_text}
        cue["proposals"] = propose_corrections(analysis_cue, output["frames"], terms, linked=True)
        independent = propose_corrections(analysis_cue, output["frames"], terms, linked=False)
        decisions = {}
        for key, value in edit.get("decisions", {}).items():
            if value not in {"accepted", "rejected", "pending"}:
                raise ValueError("纠词决定须为 accepted、rejected 或 pending")
            if str(key).isdigit():
                reference = previous_proposals if previous_proposals is not None else cue["proposals"]
                if int(key) >= len(reference):
                    raise ValueError("纠词候选编号已失效，请重新读取处理记录")
                key = proposal_key(reference[int(key)])
            decisions[str(key)] = value
        if "decisions" in edit:
            edit["decisions"] = decisions
        cue["text"] = edit.get("text", apply_corrections(base_text, cue["proposals"], decisions))
        if not isinstance(cue["text"], str) or not cue["text"].strip() or len(cue["text"]) > 2000:
            raise ValueError("字幕正文不能为空或超过 2000 字符")
        cue["independent_text"] = apply_corrections(base_text, independent)
        cue["bindings"] = bind_regions(cue, cue["text"], output["frames"], terms)
        cue["pending"] = sum(decision_for(proposal, i, decisions) == "pending" for i, proposal in enumerate(cue["proposals"]))
    output["cues"].sort(key=lambda cue: (cue["start"], cue["end"], cue["id"]))
    for before, after in zip(output["cues"], output["cues"][1:]):
        if after["start"] < before["end"] - 0.001:
            raise ValueError("当前版本支持单轨字幕，字幕时段不能重叠，请调整时间或分轨导入")
    metadata = output["metadata"]
    output["plans"] = {mode: plan(output["cues"], output["frames"], output["profile"]["id"], output["settings"], mode,
                                    metadata["width"], metadata["height"], output["settings"].get("regions", [])) for mode in ("A", "B", "C")}
    output["estimates"] = {mode: estimated_metrics(placements, output["cues"]) for mode, placements in output["plans"].items()}
    output["summary"] = {"cues": len(output["cues"]), "corrections": sum(c["text"] != c["original"] for c in output["cues"]),
                         "bindings": sum(bool(c["bindings"]) for c in output["cues"]), "pending": sum(c["pending"] for c in output["cues"]),
                         "adaptive_cues": len({p["id"] for p in output["plans"]["C"] if p["dynamic"]}),
                         "within_cue_changes": output["estimates"]["C"]["within_cue_changes"]}
    return refresh_review(output)


def save_exports(result: dict, job_dir: Path) -> None:
    for mode, placements in result["plans"].items():
        # SRT carries no positions: keep each edited cue once, even if its ASS
        # representation changes position several times during the same sentence.
        cues = [{"start": c["start"], "end": c["end"], "text": c["original"] if mode == "A" else
                 c.get("independent_text", c["text"]) if mode == "B" else c["text"]} for c in result["cues"]]
        (job_dir / f"subtitles-{mode}.srt").write_text(write_srt(cues), "utf-8")
        (job_dir / f"subtitles-{mode}.ass").write_text(write_ass(placements, result["metadata"]["width"], result["metadata"]["height"]), "utf-8")
    write_json(job_dir / "result.json", result)


def process(video: Path, job_dir: Path, settings: dict | None = None, srt: str | None = None,
            model: str = "small", cache_dir: Path | None = None, progress=lambda *_: None) -> dict:
    started = time.monotonic()
    job_dir.mkdir(parents=True, exist_ok=True)
    if video.is_file() and video.stat().st_size > MAX_VIDEO_BYTES:
        raise ValueError("视频最大 2 GB")
    metadata = probe(video)
    requested = settings or {}
    default_font = STYLES.get(requested.get("style", "professional"), STYLES["professional"])["font"]
    settings = settings_check({"profile": "auto", "style": "professional", "font": default_font, "font_scale": 1.0, "glossary": "", "regions": [], "pins": {}, **requested})
    frames = extract_frames(video, job_dir, metadata, progress)
    recognize_frames(frames, job_dir, progress)
    if srt:
        cues = parse_srt(srt)
        asr = {"engine": "provided-srt", "model": None, "word_timing": False}
        progress(0.81, "已读取提供的字幕")
    else:
        screen_text = " ".join(item["text"] for frame in frames for item in frame["ocr"])
        profile = detect_profile(screen_text, settings["profile"])
        terms = load_terms(profile["id"], settings.get("glossary", "")) + visible_terms(frames)
        hints = list(dict.fromkeys(term["text"] for term in terms if screen_evidence(term["text"], frames)))[:24]
        cues, asr = transcribe(video, metadata, model, cache_dir or job_dir.parent / ".cache", progress, job_dir / "audio.wav", hints, None if settings.get("language", "auto") == "auto" else settings["language"], settings["audio_content"])
    # Reject mismatched SRT rather than silently truncating its timeline.
    if any(cue["end"] > metadata["duration"] + 0.1 for cue in cues):
        raise ValueError("字幕时间超过视频长度，请检查 SRT 是否对应此视频")
    progress(0.85, "关联术语与画面区域，计算 A/B/C 布局")
    result = replan({"version": __version__, "metadata": metadata, "asr": asr, "settings": settings,
                     "frames": frames, "cues": cues, "edits": {}, "warnings": [
                         "题材识别使用关键词规则；游戏保护区是可修改的预设。",
                         "画面按间隔抽样，短暂出现或模糊的文字可能漏检。",
                         "句内避让在抽样帧观察到变化后调整，可能滞后一个抽样间隔；不是逐帧对象追踪。",
                         "联动使用词、时间和区域关联，尚未进行独立真实视频效果评测。"
                     ]})
    result["processing_seconds"] = round(time.monotonic() - started, 2)
    save_exports(result, job_dir)
    progress(1.0, "处理完成，可以检查和导出")
    return result
