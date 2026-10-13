"""Explicit, reversible line operations; no inferred or evenly spread timings."""
from __future__ import annotations

import copy
import math


def line_operation(result: dict, payload: dict):
    from .lyrics import align_lines
    rows = result["lines"]
    selected = payload.get("id")
    if isinstance(selected, bool) or not isinstance(selected, int):
        raise ValueError("请选择有效的歌词编号")
    index = next((i for i, row in enumerate(rows) if row["id"] == selected), None)
    if index is None:
        raise ValueError("歌词编号不存在")
    row = rows[index]
    action = payload["action"]
    if action == "split":
        at = payload.get("at")
        if isinstance(at, bool) or not isinstance(at, int) or not 0 < at < len(row["text"]):
            raise ValueError("将光标放在歌词中间，再拆成两句")
        left, right = row["text"][:at].strip(), row["text"][at:].strip()
        if not left or not right:
            raise ValueError("拆分后的两句都需要正文")
        following = copy.deepcopy(row)
        following["id"] = max(r["id"] for r in rows) + 1
        row["text"], following["text"] = left, right
        if row["start"] is not None:
            cut = payload.get("time")
            if isinstance(cut, bool) or not isinstance(cut, (int, float)) or not math.isfinite(cut) or not row["start"] < cut < row["end"]:
                raise ValueError("先将播放位置移到这句中间，用真实播放时间拆分")
            row["end"], following["start"] = round(cut, 3), round(cut, 3)
        rows.insert(index + 1, following)
        changed = [row, following]
    elif action == "merge":
        if index + 1 >= len(rows):
            raise ValueError("最后一句没有下一句可合并")
        following = rows[index + 1]
        row["text"] += " " + following["text"]
        row["original"] += "\n" + following["original"]
        if row["start"] is not None and following["start"] is not None:
            row["end"] = following["end"]
        else:
            row["start"] = row["end"] = None
        rows.pop(index + 1)
        changed = [row]
    elif action == "delete":
        if len(rows) == 1:
            raise ValueError("至少保留一句；可以修改最后一句的文字")
        rows.pop(index)
        return
    elif action == "align-range":
        start, end = payload.get("start"), payload.get("end")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (start, end)) or not 0 <= start < end <= result["metadata"]["duration"]:
            raise ValueError("请指定音频内的有效起止范围")
        words = [w for w in (result.get("recognition") or {}).get("words", [])
                 if start <= w["start"] <= w["end"] <= end]
        if not words:
            raise ValueError("这段音频没有已识别的文字锚点，请手动定位或扩大范围")
        rows[index] = align_lines([row], words, result["metadata"]["duration"])[0]
        rows[index]["timing_source"] = "asr-range"
        return
    else:
        raise ValueError("不支持的歌词行操作")
    for item in changed:
        item.update(reviewed=False, timing_source="manual-" + action,
                    issues=["歌词已拆分或合并，请重新试听"], coverage=None)
        item.pop("anchor_text", None)
