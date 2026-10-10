"""Review stamps and compact, persistent edit history shared by UI and Skill."""
from __future__ import annotations

import copy
import hashlib
import json
import re

HISTORY_LIMIT = 30


class StaleRevision(ValueError):
    pass


def check_revision(result: dict, expected: int | None) -> None:
    if expected is not None and (type(expected) is not int or expected != result.get("revision", 0)):
        raise StaleRevision("字幕已在另一个页面更新。请重新打开任务后再修改。")


def refresh_review(result: dict) -> dict:
    """A manual C-mode review applies to the exact text, timing and layout seen."""
    marks = result.setdefault("review_marks", {})
    valid = {}
    placements = {}
    for placement in result["plans"]["C"]:
        placements.setdefault(placement["id"], []).append(placement)
    for cue in result["cues"]:
        layout = placements.get(cue["id"], [])
        decisions = result.get("edits", {}).get(str(cue["id"]), {}).get("decisions", {})
        evidence = {"text": cue["text"], "start": cue["start"], "end": cue["end"],
                    "pending": cue["pending"], "decisions": decisions,
                    "layout": [{key: p.get(key) for key in ("start", "end", "rect", "text", "font", "font_size",
                               "outline", "background", "needs_review", "protected_labels")} for p in layout]}
        stamp = hashlib.sha256(json.dumps(evidence, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        cue["review_stamp"] = stamp
        cue["reviewed"] = marks.get(str(cue["id"])) == stamp
        cue["layout_review"] = any(p["needs_review"] for p in layout)
        if cue["reviewed"]:
            valid[str(cue["id"])] = stamp
    result["review_marks"] = valid
    result.setdefault("revision", 0)
    result["summary"].update(reviewed=sum(c["reviewed"] for c in result["cues"]),
                             unreviewed=sum(not c["reviewed"] for c in result["cues"]),
                             layout_review=sum(c["layout_review"] for c in result["cues"]))
    history = result.get("edit_history", {})
    result["history"] = {"undo": len(history.get("undo", [])), "redo": len(history.get("redo", [])),
                         "limit": HISTORY_LIMIT}
    return result


def _snapshot(result: dict, label: str) -> dict:
    return {"label": label, **{key: copy.deepcopy(result.get(key, {}))
            for key in ("settings", "edits", "review_marks")}}


def _commit(before: dict, after: dict, label: str) -> dict:
    history = copy.deepcopy(before.get("edit_history", {"undo": [], "redo": []}))
    history["undo"] = (history.get("undo", []) + [_snapshot(before, label)])[-HISTORY_LIMIT:]
    history["redo"] = []
    after["edit_history"] = history
    after["revision"] = before.get("revision", 0) + 1
    return refresh_review(after)


def revise_result(result: dict, payload: dict) -> dict:
    from .pipeline import replan
    check_revision(result, payload.get("revision"))
    for key in ("settings", "edits"):
        if key in payload and not isinstance(payload[key], dict):
            raise ValueError("设置与字幕修改须为对象")
    known = {str(c["id"]) for c in result["cues"]}
    if any(str(key) not in known or not isinstance(value, dict) for key, value in payload.get("edits", {}).items()):
        raise ValueError("字幕编号或修改内容无效")
    after = replan(result, payload.get("settings", {}), payload.get("edits", {}))
    if _snapshot(result, "") == _snapshot(after, "") and result.get("plans") == after["plans"]:
        return refresh_review(after)
    return _commit(result, after, "修改字幕或布局")


def _cue_ids(result: dict, ids: list | None) -> set[int]:
    known = {c["id"] for c in result["cues"]}
    if ids is None:
        return known
    if not isinstance(ids, list) or any(type(i) is not int or i not in known for i in ids):
        raise ValueError("请提供有效的字幕编号列表")
    return set(ids)


def mark_review(result: dict, payload: dict) -> dict:
    check_revision(result, payload.get("revision"))
    ids = _cue_ids(result, payload.get("ids", []))
    reviewed = payload.get("reviewed", True)
    if type(reviewed) is not bool:
        raise ValueError("复核状态须为布尔值")
    after = refresh_review(copy.deepcopy(result))
    if reviewed:
        unresolved = next((c for c in after["cues"] if c["id"] in ids and c["pending"]), None)
        if unresolved:
            raise ValueError(f"第 {unresolved['id']} 条还有待确认纠词，请先采用或保留原词")
    for cue in after["cues"]:
        if cue["id"] in ids:
            if reviewed:
                after["review_marks"][str(cue["id"])] = cue["review_stamp"]
            else:
                after["review_marks"].pop(str(cue["id"]), None)
    if after["review_marks"] == result.get("review_marks", {}):
        return after
    return _commit(result, after, "标记人工复核" if reviewed else "取消人工复核")


def replacement_preview(result: dict, payload: dict, limit: int | None = 100) -> dict:
    check_revision(result, payload.get("revision"))
    needle, replacement = payload.get("find", ""), payload.get("replace", "")
    if not isinstance(needle, str) or not needle.strip() or len(needle) > 200:
        raise ValueError("查找内容须为 1 至 200 字符")
    if not isinstance(replacement, str) or len(replacement) > 2000:
        raise ValueError("替换内容不能超过 2000 字符")
    sensitive, whole = payload.get("case_sensitive", True), payload.get("whole_word", True)
    if type(sensitive) is not bool or type(whole) is not bool:
        raise ValueError("匹配选项须为布尔值")
    ids = _cue_ids(result, payload.get("ids"))
    pattern = re.escape(needle)
    # Chinese literals need no word boundary; Latin identifiers do. Do not
    # replace LoRA inside LoRA2 or my_LoRA, or interpret replacement as regex.
    if whole and re.match(r"[A-Za-z0-9_]", needle[0]):
        pattern = r"(?<![A-Za-z0-9_])" + pattern
    if whole and re.match(r"[A-Za-z0-9_]", needle[-1]):
        pattern += r"(?![A-Za-z0-9_])"
    regex = re.compile(pattern, 0 if sensitive else re.IGNORECASE)
    matches = []
    for cue in result["cues"]:
        if cue["id"] not in ids:
            continue
        changed, count = regex.subn(lambda _: replacement, cue["text"])
        if count and changed != cue["text"]:
            if not changed.strip() or len(changed) > 2000:
                raise ValueError(f"第 {cue['id']} 条替换后为空或超过 2000 字符，请调整替换内容")
            matches.append({"id": cue["id"], "before": cue["text"], "after": changed, "count": count})
    return {"revision": result.get("revision", 0), "cues": len(matches),
            "occurrences": sum(m["count"] for m in matches),
            "matches": matches if limit is None else matches[:limit],
            "omitted": 0 if limit is None else max(0, len(matches) - limit)}


def replace_result(result: dict, payload: dict) -> dict:
    preview = replacement_preview(result, payload, limit=None)
    if not preview["cues"]:
        return refresh_review(copy.deepcopy(result))
    edits = {str(m["id"]): {**result.get("edits", {}).get(str(m["id"]), {}), "text": m["after"]}
             for m in preview["matches"]}
    from .pipeline import replan
    return _commit(result, replan(result, edits=edits), "批量替换术语")


def travel_history(result: dict, payload: dict) -> dict:
    check_revision(result, payload.get("revision"))
    action = payload.get("action", "undo")
    if action not in {"undo", "redo"}:
        raise ValueError("历史操作须为 undo 或 redo")
    other = "redo" if action == "undo" else "undo"
    history = copy.deepcopy(result.get("edit_history", {"undo": [], "redo": []}))
    if not history.get(action):
        raise ValueError("没有可撤销的修改" if action == "undo" else "没有可重做的修改")
    snapshot = history[action].pop()
    history[other] = (history.get(other, []) + [_snapshot(result, snapshot["label"])])[-HISTORY_LIMIT:]
    base = copy.deepcopy(result)
    for key in ("settings", "edits", "review_marks"):
        base[key] = copy.deepcopy(snapshot[key])
    from .pipeline import replan
    after = replan(base)
    after["revision"] = result.get("revision", 0) + 1
    after["edit_history"] = history
    return refresh_review(after)
