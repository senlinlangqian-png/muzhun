"""Line-level lyrics timing from ordered ASR anchors, with explicit unknowns.

This is assisted alignment, not a singing-specific forced aligner. Supplied
lyrics remain the text authority; unmatched lines never receive invented times.
"""
from __future__ import annotations

import copy
import functools
import math
import re
import subprocess
import unicodedata
import wave
from pathlib import Path

from . import __version__
from .editing import check_revision
from .media import MAX_DURATION, whisper_model, write_json
from .limits import LANGUAGES, MAX_TEXT_CHARS, MAX_LYRIC_LINES
from .subtitles import parse_srt, write_srt

MODELS = {"tiny", "base", "small", "medium", "large-v3-turbo"}
TIME_TAG = re.compile(r"\[(\d{1,4}):(\d{2})(?:[.:](\d{1,3}))?\]")
META_TAG = re.compile(r"^\[([a-z]{1,12}):(.*?)\]$", re.I)
OVERLAP_ISSUES = {"与下一行时间重叠", "与上一行时间重叠"}


@functools.lru_cache(maxsize=1)
def chinese_converter():
    from opencc import OpenCC
    return OpenCC("t2s")


def simplified(text: str) -> str:
    return chinese_converter().convert(text)


def units(text: str) -> list[str]:
    # Keep CJK characters separate even when a decoder groups several of them.
    # Script normalization is for matching only; supplied wording is unchanged.
    normalized = unicodedata.normalize("NFKC", simplified(text)).casefold()
    return re.findall(r"[\u3400-\u9fff\uf900-\ufaff]|[^\W_\u3400-\u9fff\uf900-\ufaff]+", normalized)


def probe_audio(path: Path) -> dict:
    import av
    with av.open(str(path)) as container:
        if not container.streams.audio:
            raise ValueError("文件没有可解码音轨")
        stream = container.streams.audio[0]
        duration = float(container.duration / av.time_base) if container.duration else float((stream.duration or 0) * stream.time_base)
        if not math.isfinite(duration) or not 0 < duration <= MAX_DURATION:
            raise ValueError("支持时长不超过 2 小时的音频")
        return {"duration": round(duration, 3), "filename": path.name}


def parse_lyrics(text: str, duration: float) -> tuple[list[dict], str]:
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError("歌词过长，请分段处理")
    if "-->" in text:
        lines = [{"text": c["original"], "start": c["start"], "end": c["end"]} for c in parse_srt(text)]
        source = "supplied-srt"
    else:
        rows, plain, offset, clears = [], [], 0.0, []
        for raw in text.splitlines():
            raw = raw.strip()
            if not raw:
                continue
            metadata = META_TAG.fullmatch(raw)
            if metadata:
                if metadata[1].lower() == "offset":
                    try:
                        offset = float(metadata[2]) / 1000
                    except ValueError as error:
                        raise ValueError("LRC offset 应为毫秒数") from error
                    if not math.isfinite(offset):
                        raise ValueError("LRC offset 无效")
                continue
            tags = list(TIME_TAG.finditer(raw))
            if tags:
                body = TIME_TAG.sub("", raw).strip()
                if re.search(r"<\d+:\d{2}", body):
                    raise ValueError("当前支持逐行 LRC，请先去掉逐字时间标签")
                for tag in tags:
                    if int(tag[2]) >= 60:
                        raise ValueError("LRC 的秒数应小于 60")
                    start = int(tag[1]) * 60 + int(tag[2]) + float("0." + (tag[3] or "0"))
                    (rows if body else clears).append({"text": body, "start": start})
            else:
                plain.append(raw)
        if rows and plain:
            raise ValueError("歌词混有带时间与不带时间的行，请分开导入，避免漏掉正文")
        if rows:
            events = sorted(rows + clears, key=lambda r: r["start"])
            for index, row in enumerate(events):
                # LRC offset is player-clock adjustment: positive means sooner.
                # The editor's explicit offset command instead shifts cue times
                # directly, so positive there means later (as labeled in UI).
                row["start"] -= offset
                row["end"] = events[index + 1]["start"] - offset if index + 1 < len(events) else duration
            lines, source = [row for row in events if row["text"]], "supplied-lrc"
        else:
            lines, source = [{"text": row, "start": None, "end": None} for row in plain], "provided-lyrics"
    if not lines or len(lines) > MAX_LYRIC_LINES or any(len(row["text"]) > 1000 for row in lines):
        raise ValueError("请提供 1–3000 行歌词，每行不超过 1000 字")
    for index, row in enumerate(lines, 1):
        row.update(id=index, original=row["text"], reviewed=False, timing_source=source,
                   coverage=None, issues=[] if source != "provided-lyrics" else ["等待音频对齐"])
    validate_lines(lines, duration)
    return lines, source


def ordered_matches(left: list[str], right: list[str]) -> dict[int, int]:
    """Global edit alignment keeps repeated choruses in their source order."""
    n, m = len(left), len(right)
    if n * m > 12_000_000:
        raise ValueError("歌词与识别结果过长，请将音频分段后对齐")
    trace = bytearray((n + 1) * (m + 1))
    previous = [-2 * j for j in range(m + 1)]
    for i, token in enumerate(left, 1):
        current = [-2 * i] + [0] * m
        base = i * (m + 1)
        for j, other in enumerate(right, 1):
            diagonal = previous[j - 1] + (3 if token == other else -3)
            up, across = previous[j] - 2, current[j - 1] - 2
            if diagonal >= up and diagonal >= across:
                current[j], trace[base + j] = diagonal, 1
            elif up >= across:
                current[j], trace[base + j] = up, 2
            else:
                current[j], trace[base + j] = across, 3
        previous = current
    matched, i, j = {}, n, m
    while i and j:
        direction = trace[i * (m + 1) + j]
        if direction == 1:
            if left[i - 1] == right[j - 1]:
                matched[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif direction == 2:
            i -= 1
        else:
            j -= 1
    return matched


def align_lines(lines: list[dict], words: list[dict], duration: float) -> list[dict]:
    result = copy.deepcopy(lines)
    left, ranges, right, timed, word_ids = [], [], [], [], []
    for row in result:
        start = len(left)
        left.extend(units(row["text"]))
        ranges.append((start, len(left)))
    for word_id, word in enumerate(words):
        try:
            start, end = float(word["start"]), float(word["end"])
        except (TypeError, KeyError, ValueError):
            continue
        if not all(math.isfinite(x) for x in (start, end)) or not 0 <= start <= min(end, duration) or start >= duration or end > duration + 0.05:
            continue
        for token in units(word["word"]):
            right.append(token)
            timed.append((start, min(end, duration)))
            word_ids.append(word_id)
    matches = ordered_matches(left, right)
    for row, (lo, hi) in zip(result, ranges):
        found = [i for i in range(lo, hi) if i in matches]
        coverage = len(found) / max(1, hi - lo)
        anchors = [matches[i] for i in found]
        matched_words = list(dict.fromkeys(word_ids[index] for index in anchors))
        row.update(coverage=round(coverage, 3), timing_source="asr-anchors", reviewed=False,
                   anchor_text="".join(words[index]["word"] for index in matched_words).strip(),
                   matched_units=len(found), lyric_units=hi - lo)
        if not found or coverage < 0.5 or (hi - lo > 2 and len(found) < 2):
            row.update(start=None, end=None, issues=["没有足够的音频文字锚点，请手动定位"])
            continue
        start, end = timed[matches[found[0]]][0], timed[matches[found[-1]]][1]
        issues = []
        if end <= start:
            row.update(start=None, end=None, issues=["锚点只有同一个时间点，请手动设置起止"])
            continue
        if any(timed[index][0] == timed[index][1] for index in anchors):
            issues.append("部分词只有时间点锚点，请核对起止")
        if coverage < 0.85:
            issues.append("歌词与识别文字匹配较少")
        if found[0] != lo or found[-1] != hi - 1:
            issues.append("句首或句尾缺少锚点")
        if end - start > max(12, (hi - lo) * 1.5):
            issues.append("跨度较长，检查是否跨过间奏或漏唱")
        if any(timed[b][0] - timed[a][1] > 3 for a, b in zip(anchors, anchors[1:])):
            issues.append("锚点之间有较长空隙，请检查间奏与错配")
        row.update(start=round(start, 3), end=round(end, 3), issues=issues)
    for previous, following in zip(result, result[1:]):
        if previous["end"] is not None and following["start"] is not None and previous["end"] > following["start"]:
            previous["issues"].append("与下一行时间重叠")
            following["issues"].append("与上一行时间重叠")
    return result


def recognition_issues(cue: dict, language: str | None) -> list[str]:
    issues = []
    if cue.get("boundary_review"):
        issues.append("分段边界补回识别词，请试听确认")
    elif cue.get("recognition_review"):
        issues.append("部分识别词把握较低，请试听确认")
    if cue.get("no_speech_prob", 0) > 0.6 or cue.get("avg_logprob", 0) < -1:
        issues.append("识别器对这段把握较低，请检查是否为伴奏或漏唱")
    if re.match(r"^(?:字幕\s*(?:by|由|[:：])|感谢(?:收看|观看)|请(?:点赞|订阅))", simplified(cue["text"]), re.I):
        issues.append("疑似字幕署名或片尾提示，请核对是否真的唱出")
    if language == "zh" and re.search(r"[a-zA-Z]{3,}", cue["text"]) and not re.search(r"[\u3400-\u9fff]", cue["text"]):
        issues.append("中文音轨中出现外文片段，请试听确认")
    return issues


def recognize_audio(path: Path, output: Path, model: str, cache: Path, language: str | None, progress, singing: bool = True, hints=None):
    from .transcription import decode_audio, recognize
    progress(.08, "解码音轨")
    target = output / "audio.wav"
    decode_audio(path, target)
    return recognize(target, model, cache, lambda value, message: progress(.15 + .65 * value, message),
                     language=language, singing=singing, hints=hints, engine_factory=whisper_model)


def process_lyrics(path: Path, output: Path, text: str, model: str, cache: Path,
                   language: str | None = None, progress=lambda *_: None, script: str = "auto", content: str = "song", glossary: str = "") -> dict:
    if content not in {"song", "speech"}:
        raise ValueError("音频类型须为 song 或 speech")
    if model not in MODELS:
        raise ValueError("不支持的语音模型")
    if language is not None and language not in LANGUAGES - {"auto"}:
        raise ValueError("不支持的语言选项")
    if script not in {"auto", "original", "simplified"}:
        raise ValueError("不支持的中文字形选项")
    metadata = probe_audio(path)
    output.mkdir(parents=True, exist_ok=True)
    lines, source = parse_lyrics(text, metadata["duration"]) if text.strip() else ([], "asr-transcript")
    asr = {"engine": "supplied-timing", "model": None}
    recognition, script_output = None, "original"
    if source not in {"supplied-lrc", "supplied-srt"}:
        from .profiles import load_terms
        hints = list(dict.fromkeys(term["text"] for term in load_terms("general", glossary)))[:64] if glossary.strip() else []
        words, cues, asr = recognize_audio(path, output, model, cache, language, progress, content == "song", hints)
        if content == "speech":
            from .transcription import speech_cues
            cues = [{**row, "text": row["original"]}
                    for row in speech_cues(words, cues, metadata["duration"])]
        recognition = {"words": copy.deepcopy(words), "segments": copy.deepcopy(cues)}
        if lines:
            progress(0.85, "按歌词顺序匹配音频锚点")
            lines = align_lines(lines, words, metadata["duration"])
        else:
            script_output = "simplified" if script == "simplified" or (script == "auto" and asr.get("language") == "zh") else "original"
            for index, row in enumerate(cues, 1):
                row.update(id=index, original=row["text"], reviewed=False, timing_source="asr-transcript",
                           coverage=None, issues=recognition_issues(row, asr.get("language")))
                if script_output == "simplified":
                    row["text"] = simplified(row["text"])
            lines = cues
        if not lines:
            raise ValueError("没有识别到歌词，请提供歌词原文，或导入已有 LRC 后手动定位")
    if not (output / "audio.wav").is_file():
        from .transcription import decode_audio
        progress(.9, "准备试听音轨与波形")
        decode_audio(path, output / "audio.wav")
    result = {"kind": "lyrics", "version": __version__, "revision": 0, "source_audio": str(path.resolve()),
              "metadata": metadata, "content": content, "text_source": source, "asr": asr, "lines": lines,
              "recognition": recognition, "script_output": script_output,
              "history": {"undo": [], "redo": []}}
    refresh(result)
    save_lyrics(result, output)
    progress(1, "歌词草稿已生成，请试听时间")
    return result


def validate_lines(lines: list[dict], duration: float):
    last_start = -1.0
    for row in lines:
        if not isinstance(row.get("text"), str) or not row["text"].strip() or len(row["text"]) > 1000:
            raise ValueError("每行歌词须为 1–1000 字的正文")
        if "\n" in row["text"] or "\r" in row["text"]:
            raise ValueError("每条只放一行歌词，请将换行分成独立条目")
        start, end = row.get("start"), row.get("end")
        if start is None and end is None:
            continue
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (start, end)):
            raise ValueError("起止时间须为有限数字，未定位时两项均留空")
        if not 0 <= start < end <= duration + 0.001:
            raise ValueError("歌词时间须位于音频内，结束须晚于开始")
        if start < last_start:
            raise ValueError("歌词起点须按正文顺序递增，请先修正相邻行")
        last_start = start


def refresh(result: dict):
    validate_lines(result["lines"], result["metadata"]["duration"])
    # Recompute timing conflicts after manual edits; old warnings must not linger.
    for row in result["lines"]:
        row["issues"] = [issue for issue in row["issues"] if issue not in OVERLAP_ISSUES]
    for previous, following in zip(result["lines"], result["lines"][1:]):
        if previous["end"] is not None and following["start"] is not None and previous["end"] > following["start"]:
            previous["issues"].append("与下一行时间重叠")
            following["issues"].append("与上一行时间重叠")
    result["summary"] = {"total": len(result["lines"]), "timed": sum(row["start"] is not None for row in result["lines"]),
                         "reviewed": sum(bool(row["reviewed"]) for row in result["lines"]),
                         "flagged": sum(bool(row["issues"]) for row in result["lines"])}
    result["summary"]["exportable"] = result["summary"]["total"] == result["summary"]["timed"]
    result["summary"]["can_realign"] = bool((result.get("recognition") or {}).get("words"))


def lyric_snapshot(result: dict) -> dict:
    return copy.deepcopy({key: result[key] for key in ("lines", "text_source", "script_output") if key in result})


def restore_snapshot(result: dict, snapshot):
    if isinstance(snapshot, list):  # 0.6 history stored just the lines.
        result["lines"] = snapshot
    else:
        for key in ("lines", "text_source", "script_output"):
            if key in snapshot:
                result[key] = snapshot[key]
            else:
                result.pop(key, None)


def revise_lyrics(before: dict, payload: dict) -> dict:
    if before.get("kind") != "lyrics":
        raise ValueError("这不是歌词处理记录")
    check_revision(before, payload.get("revision"))
    result = copy.deepcopy(before)
    history = result["history"]
    action = payload.get("action", "edit")
    if action in {"undo", "redo"}:
        source, target = ("undo", "redo") if action == "undo" else ("redo", "undo")
        if not history[source]:
            return result
        history[target] = (history[target] + [lyric_snapshot(result)])[-30:]
        restore_snapshot(result, history[source].pop())
    elif action in {"split", "merge", "delete", "align-range"}:
        from .lyric_edits import line_operation
        line_operation(result, payload)
    elif action == "realign":
        text = payload.get("lyrics")
        if not isinstance(text, str):
            raise ValueError("请提供完整歌词，重复段落也按演唱顺序写全")
        lines, source = parse_lyrics(text, result["metadata"]["duration"])
        if source == "provided-lyrics":
            words = (result.get("recognition") or {}).get("words")
            if not words:
                raise ValueError("旧记录未保存逐词锚点，请重新上传音频；也可导入已有 LRC/SRT 保留时间")
            lines = align_lines(lines, words, result["metadata"]["duration"])
        result.update(lines=lines, text_source=source, script_output="original")
    elif action == "simplify":
        for row in result["lines"]:
            text = simplified(row["text"])
            if text != row["text"]:
                row.update(text=text, reviewed=False, issues=["中文字形已修改，请核对原文"], coverage=None)
                row.pop("anchor_text", None)
        result["script_output"] = "simplified"
    elif action == "edit":
        edits = payload.get("edits", [])
        if not isinstance(edits, list) or len(edits) > MAX_LYRIC_LINES:
            raise ValueError("edits 须为歌词修改列表")
        known = {row["id"]: row for row in result["lines"]}
        for edit in edits:
            if not isinstance(edit, dict) or isinstance(edit.get("id"), bool) or edit.get("id") not in known:
                raise ValueError("歌词编号不存在")
            row = known[edit["id"]]
            changed = any(key in edit and edit[key] != row[key] for key in ("text", "start", "end"))
            if changed:
                for key in ("text", "start", "end"):
                    if key in edit:
                        row[key] = edit[key]
                row.update(reviewed=False, timing_source="manual", issues=["手动修改后请重新试听"])
                if "text" in edit:
                    row["coverage"] = None
                    row.pop("anchor_text", None)
            if "reviewed" in edit:
                if not isinstance(edit["reviewed"], bool):
                    raise ValueError("reviewed 须为布尔值")
                if edit["reviewed"] and (row["start"] is None or changed):
                    raise ValueError("先保存完整时间，再试听并标记复核")
                row["reviewed"] = edit["reviewed"]
        offset = payload.get("offset", 0)
        if isinstance(offset, bool) or not isinstance(offset, (int, float)) or not math.isfinite(offset) or abs(offset) > 60:
            raise ValueError("整体偏移须为 -60 到 60 秒之间的数字")
        if offset:
            for row in result["lines"]:
                if row["start"] is not None:
                    row.update(start=round(row["start"] + offset, 3), end=round(row["end"] + offset, 3),
                               reviewed=False, timing_source="manual-offset", issues=["整体偏移后请重新试听"])
    else:
        raise ValueError("不支持的歌词操作")
    if action not in {"undo", "redo"}:
        if lyric_snapshot(result) == lyric_snapshot(before):
            return result
        history["undo"] = (history["undo"] + [lyric_snapshot(before)])[-30:]
        history["redo"] = []
    result["version"] = __version__
    result["revision"] += 1
    refresh(result)
    return result


def lrc_timestamp(seconds: float) -> str:
    ticks = int(seconds * 100 + 0.5)
    minutes, rest = divmod(ticks, 6000)
    second, fraction = divmod(rest, 100)
    return f"[{minutes:02d}:{second:02d}.{fraction:02d}]"


def write_lrc(lines: list[dict]) -> str:
    output = []
    for index, row in enumerate(lines):
        output.append(lrc_timestamp(row["start"]) + row["text"].replace("\n", " ").replace("\r", " "))
        # Blank events clear the previous line during an instrumental gap.
        next_start = lines[index + 1]["start"] if index + 1 < len(lines) else math.inf
        if row["end"] + 0.75 < next_start:
            output.append(lrc_timestamp(row["end"]))
    return "\n".join(output) + "\n"


def save_lyrics(result: dict, output: Path):
    refresh(result)
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "lyrics-result.json", result)
    if result["summary"]["exportable"]:
        (output / "lyrics.lrc").write_text(write_lrc(result["lines"]), "utf-8")
        (output / "lyrics.srt").write_text(write_srt(result["lines"]), "utf-8")
    else:
        for name in ("lyrics.lrc", "lyrics.srt"):
            (output / name).unlink(missing_ok=True)
