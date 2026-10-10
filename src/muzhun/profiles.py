from __future__ import annotations

import json
import math
import re
from pathlib import Path

PROFILES = json.loads((Path(__file__).parent / "data" / "profiles.json").read_text("utf-8"))


def detect_profile(text: str, requested: str = "auto") -> dict:
    if requested != "auto":
        if requested not in PROFILES:
            raise ValueError("不支持的题材")
        return {"id": requested, "label": PROFILES[requested]["label"], "confidence": None,
                "source": "user", "evidence": [], "message": "由用户指定"}
    lower = text.lower()
    scores = []
    for key, profile in PROFILES.items():
        hits = [{"text": word, "weight": weight} for word, weight in profile["keywords"].items()
                if (re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", lower)
                    if re.fullmatch(r"[a-z0-9-]+", word) else word in lower)]
        score = sum(hit["weight"] for hit in hits)
        scores.append((score, key, hits))
    scores.sort(reverse=True)
    top, key, hits = scores[0]
    runner = scores[1][0]
    # This is a heuristic score, not a calibrated probability.
    if top < 4 or (runner >= 4 and top - runner < 3):
        return {"id": "general", "label": "通用内容", "confidence": 0.0,
                "source": "rules", "evidence": hits, "message": "题材依据不足或混合，请按需要手动指定"}
    confidence = round(min(0.95, 0.45 + 0.35 * (1 - math.exp(-top / 6)) + 0.15 * (top - runner) / top), 2)
    return {"id": key, "label": PROFILES[key]["label"], "confidence": confidence,
            "source": "rules", "evidence": hits, "message": "基于画面文字与字幕关键词的判断，分数不代表准确率"}


def load_terms(profile_id: str, extra: str = "") -> list[dict]:
    terms = [dict(term) for term in PROFILES[profile_id]["terms"]]
    # One canonical term per line; optional aliases after =, separated by |.
    for line in extra.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        canonical, sep, aliases = line.partition("=")
        canonical = canonical.strip()
        if len(canonical) > 80:
            raise ValueError("单个术语最多 80 个字符")
        if canonical:
            terms.append({"text": canonical, "aliases": [a.strip() for a in aliases.split("|") if a.strip()] if sep else []})
    unique = {}
    for term in terms:
        unique.setdefault(term["text"], {"text": term["text"], "aliases": []})
        unique[term["text"]]["aliases"] = sorted(set(unique[term["text"]]["aliases"] + term["aliases"]))
    return list(unique.values())
