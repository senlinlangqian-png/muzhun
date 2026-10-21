from __future__ import annotations

import math
import os
import re
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from .evidence import nearby_frames
from .profiles import PROFILES

STYLES = {
    "professional": {"label": "专业清晰", "font": "sans", "scale": 0.055, "outline": 2, "background": True},
    "gaming": {"label": "游戏醒目", "font": "bold", "scale": 0.062, "outline": 3, "background": False},
    "minimal": {"label": "简洁通用", "font": "sans", "scale": 0.048, "outline": 2, "background": False},
}


@lru_cache(maxsize=16)
def font_path(choice: str = "sans") -> tuple[str, str]:
    custom = os.environ.get("MUZHUN_FONT")
    windir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    if custom:
        if not Path(custom).is_file():
            raise RuntimeError("MUZHUN_FONT 指定的字体文件不存在")
        # libass needs the font's actual family name, not a placeholder name.
        return custom, ImageFont.truetype(custom, 24).getname()[0]
    candidates = []
    if choice == "bold":
        candidates += [(str(windir / "msyhbd.ttc"), "Microsoft YaHei"), ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "Noto Sans CJK SC")]
    candidates += [(str(windir / "msyh.ttc"), "Microsoft YaHei"), ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK SC"), ("/System/Library/Fonts/PingFang.ttc", "PingFang SC")]
    bundled = Path(__file__).resolve().parents[2] / ".cache/fonts/NotoSansCJKsc-Regular.otf"
    candidates.append((str(bundled), "Noto Sans CJK SC"))
    if choice == "mono":
        candidates.insert(0, (str(windir / "Deng.ttf"), "DengXian"))
    for path, family in candidates:
        if path and Path(path).is_file():
            return path, family
    raise RuntimeError("未找到中文字体。安装 Noto Sans CJK，或用 MUZHUN_FONT 指定字体文件。")


@lru_cache(maxsize=48)
def get_font(choice: str, size: int):
    return ImageFont.truetype(font_path(choice)[0], size)


def overlap(a: list[float], b: list[float]) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def union_area(rects: list[list[float]]) -> float:
    if not rects:
        return 0.0
    xs = sorted({v for rect in rects for v in (rect[0], rect[2])})
    area = 0.0
    for left, right in zip(xs, xs[1:]):
        intervals = sorted((r[1], r[3]) for r in rects if r[0] < right and r[2] > left)
        height = 0.0
        low = high = None
        for start, end in intervals:
            if low is None:
                low, high = start, end
            elif start <= high:
                high = max(high, end)
            else:
                height += high - low
                low, high = start, end
        if low is not None:
            height += high - low
        area += (right - left) * height
    return area


def wrap_text(text: str, max_width: float, font) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9_./+\-]+|\s+|[^A-Za-z0-9_./+\-\s]", text)
    lines = []
    current = ""
    for token in tokens:
        if font.getlength(current + token) <= max_width:
            current += token
            continue
        if current.strip():
            lines.append(current.strip())
            current = ""
        # Extremely long identifiers must still fit inside the image.
        if font.getlength(token) > max_width:
            for char in token:
                if current and font.getlength(current + char) > max_width:
                    lines.append(current.strip())
                    current = ""
                current += char
        else:
            current = token.lstrip()
    if current.strip():
        lines.append(current.strip())
    return lines or [""]


def base_regions(cue: dict, frames: list[dict], profile_id: str, custom: list[dict]) -> list[dict]:
    regions = []
    for frame in nearby_frames(cue, frames):
        for item in frame["ocr"]:
            if item["confidence"] >= 0.70:
                regions.append({"rect": item["rect"], "label": item["text"], "source": "ocr", "weight": 1.5})
    regions.extend({**guard, "source": "profile"} for guard in PROFILES[profile_id]["guards"])
    regions.extend({**region, "source": "user", "weight": 12} for region in custom
                   if region.get("start", 0) < cue["end"] and region.get("end", float("inf")) > cue["start"])
    unique = {}
    for region in regions:
        unique[(tuple(region["rect"]), region["source"])] = region
    return list(unique.values())


def _candidates(text: str, width: int, height: int, settings: dict, mode: str) -> list[dict]:
    preset = STYLES[settings.get("style", "professional")]
    choice = settings.get("font", preset["font"])
    size = round(height * preset["scale"] * settings.get("font_scale", 1.0))
    size = max(14, min(100, size))
    font = get_font(choice, size)
    padding = max(6, round(size * 0.30))
    anchors = [(0.5, 0.88, "下方"), (0.5, 0.12, "上方"), (0.24, 0.82, "左下"), (0.76, 0.82, "右下"),
               (0.24, 0.20, "左上"), (0.76, 0.20, "右上"), (0.24, 0.51, "左侧"), (0.76, 0.51, "右侧")]
    if mode == "A":
        anchors = anchors[:1]
    ratios = [0.84] if mode != "C" else [0.84, 0.64, 0.45]
    candidates = []
    for ratio in ratios:
        lines = wrap_text(text, width * ratio - 2 * padding, font)
        lengths = [font.getlength(line) for line in lines]
        bw = min(width * 0.94, max(lengths) + 2 * padding)
        bh = len(lines) * size * 1.35 + 2 * padding
        if bh > height * 0.70:
            continue
        for cx, cy, label in anchors:
            left = max(width * 0.03, min(width * cx - bw / 2, width * 0.97 - bw))
            top = max(height * 0.03, min(height * cy - bh / 2, height * 0.97 - bh))
            candidates.append({"text": "\n".join(lines), "rect": [round(left / width, 5), round(top / height, 5), round((left + bw) / width, 5), round((top + bh) / height, 5)],
                               "x": round(left + bw / 2), "y": round(top + bh / 2), "font_size": size,
                               "font": choice, "font_family": font_path(choice)[1], "label": label,
                               "line_count": len(lines), "outline": preset["outline"], "background": preset["background"],
                               "raggedness": max(0, .5 - lengths[-1] / max(1, max(lengths))) * 2 if len(lines) > 1 else 0})
    if not candidates:
        raise ValueError("字幕过长，无法保持可读字号，请先分段")
    return list({_candidate_key(candidate): candidate for candidate in candidates}.values())


def _candidate_key(candidate: dict) -> tuple:
    return tuple(candidate["rect"]), candidate["text"]


def _cost(candidate: dict, regions: list[dict], focus: list[dict], mode: str) -> float:
    rect = candidate["rect"]
    area = max(0.0001, (rect[2] - rect[0]) * (rect[3] - rect[1]))
    def covered(region):
        box = region["rect"]
        protected_area = max(0.0001, (box[2] - box[0]) * (box[3] - box[1]))
        return overlap(rect, box) / min(area, protected_area) * region["weight"]
    # A large caption must not dilute the cost of covering a small title.
    occlusion = sum(covered(region) for region in regions)
    if mode == "C":
        occlusion += sum(covered(region) for region in focus)
    reading = max(0, candidate["line_count"] - 2) * 4 + candidate.get("raggedness", 0)
    preference = 0 if candidate["label"] == "下方" else 0.20 if candidate["label"] == "上方" else 0.45
    return occlusion * 6 + reading + preference


def _transition(before: dict, after: dict, gap: float) -> float:
    if gap > 1.5:
        return 0.0
    distance = math.hypot((before["rect"][0] + before["rect"][2] - after["rect"][0] - after["rect"][2]) / 2,
                          (before["rect"][1] + before["rect"][3] - after["rect"][1] - after["rect"][3]) / 2)
    return distance * 2.8 + (0.6 if before["label"] != after["label"] else 0.0)


MIN_HOLD_SECONDS = 1.2


def _timeline(cue: dict, frames: list[dict], profile_id: str, custom: list[dict], adaptive: bool) -> list[dict]:
    """Sample-and-hold observations; change times are estimates, not tracking."""
    if not adaptive:
        focus = list({(tuple(b["rect"]), b["label"]): b for b in cue.get("bindings", [])}.values())
        return [{"start": cue["start"], "end": cue["end"], "regions": base_regions(cue, frames, profile_id, custom),
                 "focus": focus, "frame_time": None, "image": None}]
    ordered = sorted(frames, key=lambda frame: frame["time"])
    cuts = {cue["start"], cue["end"]}
    cuts.update(round(f["time"], 2) for f in ordered if cue["start"] < f["time"] < cue["end"])
    for region in custom:
        cuts.update(round(region[key], 2) for key in ("start", "end") if key in region and cue["start"] < region[key] < cue["end"])
    # Do not create events too short to survive ASS's centisecond clock.
    boundaries = [cue["start"]]
    boundaries.extend(t for t in sorted(cuts) if t - boundaries[-1] >= .02 and cue["end"] - t >= .02)
    boundaries.append(cue["end"])
    timeline = []
    for start, end in zip(boundaries, boundaries[1:]):
        previous = [f for f in ordered if f["time"] <= start + .005]
        # If the initial observation starts late, use the first in-cue sample
        # for the leading interval. Normal extraction includes the initial frame.
        observed = previous[-1] if previous else next((f for f in ordered if start < f["time"] < cue["end"]), None)
        regions = [{**guard, "source": "profile"} for guard in PROFILES[profile_id]["guards"]]
        regions.extend({**region, "source": "user", "weight": 12} for region in custom
                       if region.get("start", 0) < end and region.get("end", float("inf")) > start)
        focus = []
        if observed:
            regions.extend({"rect": item["rect"], "label": item["text"], "source": "ocr", "weight": 1.5}
                           for item in observed["ocr"] if item["confidence"] >= .70)
            focus = [b for b in cue.get("bindings", []) if b["image"] == observed["image"] and b["time"] == observed["time"]]
        timeline.append({"start": start, "end": end, "regions": regions, "focus": focus,
                         "frame_time": observed["time"] if observed else None, "image": observed["image"] if observed else None})
    return timeline


def _choose(units: list[dict], mode: str) -> list[int]:
    if mode != "C":
        return [min(range(len(unit["local"])), key=unit["local"].__getitem__) for unit in units]
    # A state retains how long its position has been held. This enforces the
    # minimum dwell across observation boundaries without greedy oscillation.
    rows = []
    for index, unit in enumerate(units):
        duration = unit["end"] - unit["start"]
        states = {}
        for picked, (choice, score) in enumerate(zip(unit["choices"], unit["local"])):
            if index == 0:
                age = round(min(MIN_HOLD_SECONDS, duration), 3)
                states[(picked, age)] = {"picked": picked, "age": age, "score": score * duration, "prev": -1}
                continue
            before = units[index - 1]
            same_cue = unit["cue"]["id"] == before["cue"]["id"]
            for previous_index, previous in enumerate(rows[-1]):
                old = before["choices"][previous["picked"]]
                changed = _candidate_key(old) != _candidate_key(choice)
                if same_cue and changed:
                    if previous["age"] < MIN_HOLD_SECONDS or unit["cue"]["end"] - unit["start"] < MIN_HOLD_SECONDS:
                        continue
                    # Staying in another safe slot is preferable to moving just
                    # to return to the default anchor when information vanishes.
                    if _cost(old, unit["regions"], unit["focus"], mode) - score < 1.0:
                        continue
                movement = _transition(old, choice, unit["start"] - before["end"])
                if same_cue and changed:
                    movement = movement * 2 + 2
                age = min(MIN_HOLD_SECONDS, previous["age"] + duration) if same_cue and not changed else min(MIN_HOLD_SECONDS, duration)
                age = round(age, 3)
                total = previous["score"] + movement + score * duration
                key = (picked, age)
                if key not in states or total < states[key]["score"]:
                    states[key] = {"picked": picked, "age": age, "score": total, "prev": previous_index}
        rows.append(list(states.values()))
    chosen = [0] * len(units)
    cursor = min(range(len(rows[-1])), key=lambda i: rows[-1][i]["score"])
    for index in range(len(units) - 1, -1, -1):
        state = rows[index][cursor]
        chosen[index], cursor = state["picked"], state["prev"]
    return chosen


def plan(cues: list[dict], frames: list[dict], profile_id: str, settings: dict, mode: str,
         width: int, height: int, custom: list[dict] | None = None) -> list[dict]:
    units = []
    for cue in cues:
        text = cue["original"] if mode == "A" else cue.get("independent_text", cue["text"]) if mode == "B" else cue["text"]
        choices = _candidates(text, width, height, settings, mode)
        pins = settings.get("pins", {})
        pin = pins.get(str(cue["id"])) if mode == "C" else None
        if pin:
            # Locking a position must not revert a readable two-line caption to
            # the first/widest wrapping with an orphaned final fragment.
            candidate = dict(min(choices, key=lambda c: max(0, c["line_count"] - 2) * 4 + c.get("raggedness", 0)))
            box_width = candidate["rect"][2] - candidate["rect"][0]
            box_height = candidate["rect"][3] - candidate["rect"][1]
            left = max(0.01, min(float(pin[0]) - box_width / 2, 0.99 - box_width))
            top = max(0.01, min(float(pin[1]) - box_height / 2, 0.99 - box_height))
            candidate.update(rect=[left, top, left + box_width, top + box_height], x=round((left + box_width / 2) * width), y=round((top + box_height / 2) * height), label="手动锁定")
            choices = [candidate]
        adaptive = mode == "C" and settings.get("position_policy", "adaptive") == "adaptive" and not pin
        for interval in _timeline(cue, frames, profile_id, custom or [], adaptive):
            units.append({**interval, "cue": cue, "choices": choices,
                          "local": [_cost(choice, interval["regions"], interval["focus"], mode) if mode != "A" else 0 for choice in choices]})
    if not units:
        return []
    chosen = _choose(units, mode)
    result = []
    for unit, picked in zip(units, chosen):
        cue = unit["cue"]
        placement = dict(unit["choices"][picked])
        placement.update(id=cue["id"], start=unit["start"], end=unit["end"], cue_start=cue["start"], cue_end=cue["end"])
        placement["focus_overlap"] = round(sum(overlap(placement["rect"], region["rect"]) for region in unit["focus"]), 6)
        ocr = [region for region in unit["regions"] if region["source"] == "ocr"]
        placement["ocr_overlap_ratio"] = round(max((overlap(placement["rect"], item["rect"]) /
            max(.0001, (item["rect"][2]-item["rect"][0])*(item["rect"][3]-item["rect"][1])) for item in ocr), default=0), 4)
        placement["needs_review"] = placement["focus_overlap"] > 0 or placement["line_count"] > 2 or placement["ocr_overlap_ratio"] > .20
        # Explicit user protection still matters when a manual pin wins over
        # the optimizer. Do not silently mark that collision as safe.
        placement["user_overlap"] = round(sum(overlap(placement["rect"], r["rect"]) for r in unit["regions"] if r["source"] == "user"), 6)
        placement["needs_review"] |= placement["user_overlap"] > 0
        placement["protected_labels"] = sorted({r.get("label", r.get("term", "保护区")) for r in unit["focus"] + unit["regions"] if r["source"] != "ocr"})
        placement["samples"] = [{key: value for key, value in {**unit, **placement}.items()
                                 if key in {"start", "end", "frame_time", "image", "focus_overlap", "ocr_overlap_ratio", "needs_review"}}]
        if result and result[-1]["id"] == cue["id"] and _candidate_key(result[-1]) == _candidate_key(placement):
            previous = result[-1]
            previous["end"] = placement["end"]
            previous["samples"].extend(placement["samples"])
            previous["focus_overlap"] = max(previous["focus_overlap"], placement["focus_overlap"])
            previous["ocr_overlap_ratio"] = max(previous["ocr_overlap_ratio"], placement["ocr_overlap_ratio"])
            previous["needs_review"] |= placement["needs_review"]
            previous["user_overlap"] = max(previous["user_overlap"], placement["user_overlap"])
            previous["protected_labels"] = sorted(set(previous["protected_labels"] + placement["protected_labels"]))
        else:
            result.append(placement)
    for cue in cues:
        segments = [p for p in result if p["id"] == cue["id"]]
        for index, segment in enumerate(segments, 1):
            segment.update(segment_index=index, segment_count=len(segments), dynamic=len(segments) > 1,
                           movement_reason="手动锁定整句" if segment["label"] == "手动锁定" else
                           "整句保持" if len(segments) == 1 else "起始位置" if index == 1 else "保护区域变化，降低遮挡")
    return result


def estimated_metrics(placements: list[dict], cues: list[dict]) -> dict:
    jumps = sum((a["x"], a["y"]) != (b["x"], b["y"]) and b["start"] - a["end"] <= 1.5 for a, b in zip(placements, placements[1:]))
    within = sum(a["id"] == b["id"] for a, b in zip(placements, placements[1:]))
    return {"focus_overlap_seconds": round(sum(s["end"] - s["start"] for p in placements for s in p.get("samples", [p]) if s["focus_overlap"] > 0), 2),
            "position_changes": jumps, "within_cue_changes": within, "layout_segments": len(placements),
            "review_cues": len({p["id"] for p in placements if p["needs_review"]}),
            "note": "根据自动绑定区域估算，非人工标注评测；不代表准确率或实际节省时间"}
