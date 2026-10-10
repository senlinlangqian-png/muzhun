from __future__ import annotations

import re


def parse_srt(text: str) -> list[dict]:
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    pattern = re.compile(r"(\d{1,3}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{1,3}):(\d{2}):(\d{2})[,.](\d{3})[^\n]*\n(.*?)(?=\n\s*\n|\Z)", re.S)
    cues = []
    for match in pattern.finditer(text.strip()):
        values = [int(v) for v in match.groups()[:8]]
        if any(values[i] >= 60 for i in (1, 2, 5, 6)):
            raise ValueError("字幕时间格式无效")
        start = values[0] * 3600 + values[1] * 60 + values[2] + values[3] / 1000
        end = values[4] * 3600 + values[5] * 60 + values[6] + values[7] / 1000
        body = re.sub(r"<[^>]+>", "", match.group(9)).strip().replace("\n", " ")
        if end <= start or not body:
            raise ValueError("字幕结束时间须晚于开始时间，正文不能为空")
        if len(body) > 2000:
            raise ValueError("单条字幕过长，请先分段")
        cues.append({"id": len(cues) + 1, "start": round(start, 3), "end": round(end, 3), "original": body})
    if not cues:
        raise ValueError("没有读取到有效 SRT 字幕")
    cues.sort(key=lambda cue: (cue["start"], cue["end"]))
    for index, cue in enumerate(cues, 1):
        cue["id"] = index
    return cues


def timestamp(seconds: float, ass: bool = False) -> str:
    scale = 100 if ass else 1000
    ticks = max(0, round(seconds * scale))
    whole, fraction = divmod(ticks, scale)
    hours, whole = divmod(whole, 3600)
    minutes, whole = divmod(whole, 60)
    return f"{hours:d}:{minutes:02d}:{whole:02d}.{fraction:02d}" if ass else f"{hours:02d}:{minutes:02d}:{whole:02d},{fraction:03d}"


def write_srt(cues: list[dict]) -> str:
    return "\n\n".join(f"{i}\n{timestamp(c['start'])} --> {timestamp(c['end'])}\n{c['text']}" for i, c in enumerate(cues, 1)) + "\n"


def ass_escape(text: str) -> str:
    # Curly braces and backslashes are ASS control syntax, not user styling.
    return text.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\r", "").replace("\n", "\\N")
