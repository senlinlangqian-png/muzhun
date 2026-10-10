from __future__ import annotations

import re
import hashlib
import json
from difflib import SequenceMatcher
from functools import lru_cache


def normalized(text: str) -> str:
    return re.sub(r"[^a-z0-9\u3400-\u9fff]", "", text.lower())


def nearby_frames(cue: dict, frames: list[dict], margin: float = 0.75) -> list[dict]:
    selected = [f for f in frames if cue["start"] - margin <= f["time"] <= cue["end"] + margin]
    return selected


def screen_evidence(term: str, frames: list[dict], limit: int | None = 8) -> list[dict]:
    target = normalized(term)
    found = []
    if len(target) < 2:
        return found
    for frame in frames:
        for item in frame["ocr"]:
            observed = normalized(item["text"])
            # Latin terms must be token-bounded: API is not evidence from capital.
            if re.fullmatch(r"[A-Za-z0-9._+ -]+", term):
                match = re.search(r"(?<![a-z0-9])" + re.escape(term.lower()).replace(r"\ ", r"\s*") + r"(?![a-z0-9])", item["text"].lower())
                matched = bool(match) or observed == target
            else:
                matched = target in observed
            if matched and item["confidence"] >= 0.70:
                found.append({"term": term, "time": frame["time"], "image": frame["image"],
                              "rect": item["rect"], "screen_text": item["text"], "confidence": item["confidence"]})
    ranked = sorted(found, key=lambda value: value["confidence"], reverse=True)
    return ranked[:limit] if limit is not None else ranked


def visible_terms(frames: list[dict]) -> list[dict]:
    ignored = {"file", "edit", "view", "help", "window", "settings", "true", "false", "none", "default", "close", "open", "cancel", "apply", "untitled", "return", "print", "import"}
    terms = {}
    for frame in frames:
        for item in frame["ocr"]:
            if item["confidence"] < 0.85:
                continue
            for token in re.findall(r"\b[A-Za-z][A-Za-z0-9_.+-]{2,30}\b", item["text"]):
                if token.lower() in ignored or not (re.search(r"[A-Z]", token[1:]) or re.search(r"[0-9_+-]", token) or token.isupper()):
                    continue
                terms.setdefault(token, {"text": token, "aliases": [token.lower()]})
            token = item["text"].strip()
            if item["confidence"] >= 0.94 and re.fullmatch(r"[\u3400-\u9fff]{2,8}", token) and token not in {"确定", "取消", "设置", "文件", "编辑", "保存", "退出", "帮助", "播放", "暂停", "下一步", "完成"}:
                terms.setdefault(token, {"text": token, "aliases": []})
    return list(terms.values())[:80]


def _alias_pattern(alias: str) -> re.Pattern:
    escaped = re.escape(alias)
    if re.fullmatch(r"[A-Za-z0-9._+ -]+", alias):
        return re.compile(r"(?<![A-Za-z0-9_])" + escaped + r"(?![A-Za-z0-9_])", re.I)
    return re.compile(escaped)


@lru_cache(maxsize=2048)
def _phonetic(text: str) -> str:
    from pypinyin import lazy_pinyin
    return " ".join(lazy_pinyin(text))


def context_rect(evidence: dict, frame: dict) -> list[float]:
    """Group adjacent OCR boxes on the same line; do not claim object detection."""
    rect = list(evidence["rect"])
    for _ in range(3):
        changed = False
        center = (rect[1] + rect[3]) / 2
        height = rect[3] - rect[1]
        for item in frame["ocr"]:
            candidate = item["rect"]
            if item["confidence"] < .80:
                continue
            other_center = (candidate[1] + candidate[3]) / 2
            gap = max(candidate[0] - rect[2], rect[0] - candidate[2], 0)
            if abs(other_center - center) <= max(.018, height * .55) and gap <= .13:
                expanded = [min(rect[0], candidate[0]), min(rect[1], candidate[1]), max(rect[2], candidate[2]), max(rect[3], candidate[3])]
                if expanded != rect:
                    rect = expanded
                    changed = True
        if not changed:
            break
    return [max(0, rect[0] - .009), max(0, rect[1] - .009), min(1, rect[2] + .009), min(1, rect[3] + .009)]


def propose_corrections(cue: dict, frames: list[dict], terms: list[dict], linked: bool = True) -> list[dict]:
    context = nearby_frames(cue, frames) if linked else frames
    text = cue["original"]
    proposals = []
    occupied = set()
    for term in terms:
        canonical = term["text"]
        evidence = screen_evidence(canonical, context)
        aliases = sorted(set(term.get("aliases", []) + [canonical]), key=len, reverse=True)
        for alias in aliases:
            if not alias:
                continue
            for match in _alias_pattern(alias).finditer(text):
                span = set(range(match.start(), match.end()))
                if match.group() == canonical or span & occupied:
                    continue
                auto = bool(evidence and evidence[0]["confidence"] >= 0.85)
                proposals.append({"start": match.start(), "end": match.end(), "from": match.group(),
                                  "to": canonical, "confidence": 0.94 if auto else 0.62,
                                  "kind": "alias", "decision": "accepted" if auto else "pending",
                                  "evidence": evidence[:3], "reason": "同时间画面文字支持" if evidence and linked else "画面词表支持" if evidence else "仅术语表支持，请听音确认"})
                occupied |= span
    # Fuzzy matching only proposes English candidates supported by the screen.
    # Phonetic Chinese aliases are explicit in the editable glossary.
    for match in re.finditer(r"\b[A-Za-z][A-Za-z0-9_-]{2,30}\b", text):
        span = set(range(match.start(), match.end()))
        if span & occupied:
            continue
        candidates = []
        for term in terms:
            canonical = term["text"]
            if canonical.lower() == match.group().lower() or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]+", canonical):
                continue
            similarity = SequenceMatcher(None, canonical.lower(), match.group().lower()).ratio()
            if 0.80 <= similarity < 1:
                evidence = screen_evidence(canonical, context)
                if evidence:
                    candidates.append((similarity, canonical, evidence))
        candidates.sort(reverse=True, key=lambda item: item[0])
        if candidates and (len(candidates) == 1 or candidates[0][0] - candidates[1][0] > 0.08):
            score, canonical, evidence = candidates[0]
            proposals.append({"start": match.start(), "end": match.end(), "from": match.group(),
                              "to": canonical, "confidence": round(score, 2), "kind": "similarity",
                              "decision": "pending", "evidence": evidence[:3], "reason": "近似拼写，需人工确认"})
    # Chinese terms read from the screen can suggest near homophones, but
    # never authorize an automatic semantic rewrite without an explicit alias.
    candidates = []
    for term in terms:
        canonical = term["text"]
        if not re.fullmatch(r"[\u3400-\u9fff]{2,8}", canonical) or canonical in text:
            continue
        evidence = screen_evidence(canonical, context)
        if not evidence:
            continue
        for group in re.finditer(r"[\u3400-\u9fff]{2,}", text):
            for offset in range(len(group.group()) - len(canonical) + 1):
                start = group.start() + offset
                end = start + len(canonical)
                source = text[start:end]
                if set(range(start, end)) & occupied or sum(a != b for a, b in zip(source, canonical)) != 1:
                    continue
                similarity = SequenceMatcher(None, _phonetic(source), _phonetic(canonical)).ratio()
                if similarity >= .90:
                    candidates.append((similarity, start, end, source, canonical, evidence))
    for similarity, start, end, source, canonical, evidence in sorted(candidates, reverse=True):
        span = set(range(start, end))
        if span & occupied:
            continue
        proposals.append({"start": start, "end": end, "from": source, "to": canonical,
                          "confidence": round(similarity, 2), "kind": "phonetic", "decision": "pending",
                          "evidence": evidence[:3], "reason": "画面中的近音词，需听音确认"})
        occupied |= span
    proposals.sort(key=lambda item: item["start"])
    for proposal in proposals:
        proposal["key"] = proposal_key(proposal)
    return proposals


def proposal_key(proposal: dict) -> str:
    payload = [proposal["start"], proposal["end"], proposal["from"], proposal["to"]]
    return "p-" + hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def decision_for(proposal: dict, index: int, decisions: dict | None = None) -> str:
    choices = decisions or {}
    return choices.get(proposal.get("key", proposal_key(proposal)), choices.get(str(index), proposal["decision"]))


def apply_corrections(text: str, proposals: list[dict], decisions: dict | None = None) -> str:
    for index, proposal in reversed(list(enumerate(proposals))):
        decision = decision_for(proposal, index, decisions)
        if decision == "accepted":
            text = text[:proposal["start"]] + proposal["to"] + text[proposal["end"]:]
    return text


def bind_regions(cue: dict, text: str, frames: list[dict], terms: list[dict]) -> list[dict]:
    context = nearby_frames(cue, frames)
    result = []
    mentioned = normalized(text)
    for term in terms:
        canonical = term["text"]
        is_mentioned = bool(_alias_pattern(canonical).search(text)) if re.fullmatch(r"[A-Za-z0-9._+ -]+", canonical) else normalized(canonical) in mentioned
        if not is_mentioned:
            continue
        # Layout needs every observation, including later appearances at the
        # same coordinates. The proposal preview may still use the best eight.
        for evidence in screen_evidence(canonical, context, limit=None):
            frame = next(f for f in context if f["image"] == evidence["image"] and f["time"] == evidence["time"])
            result.append({**evidence, "screen_rect": evidence["rect"], "rect": context_rect(evidence, frame),
                           "label": canonical, "source": "binding", "weight": 8})
    # Exact longer screen phrases can bind named UI buttons and Chinese labels.
    for frame in context:
        for item in frame["ocr"]:
            candidate = normalized(item["text"])
            label = item["text"].strip()
            matches = bool(_alias_pattern(label).search(text)) if re.fullmatch(r"[A-Za-z0-9._+ -]+", label) else candidate in mentioned
            # Bare row numbers are ambiguous. Keep them in general OCR avoidance,
            # but do not turn 01 inside 0.001 into a semantic focus binding.
            if 2 <= len(candidate) <= 24 and not candidate.isdigit() and matches and item["confidence"] >= 0.80:
                result.append({"term": item["text"], "label": item["text"], "time": frame["time"],
                               "image": frame["image"], "rect": item["rect"], "screen_text": item["text"],
                               "confidence": item["confidence"], "source": "binding", "weight": 8})
    unique = {}
    for item in result:
        unique[(item["time"], item["image"], tuple(item["rect"]), item["label"])] = item
    return sorted(unique.values(), key=lambda item: (item["time"], item["label"]))
