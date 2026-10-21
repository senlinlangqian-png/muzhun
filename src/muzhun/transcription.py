"""Bounded-memory, resumable ASR with real time offsets and overlap context."""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import wave
from pathlib import Path

from .limits import MAX_DURATION

# Keep even the context window below Whisper's native 30-second input.
# Longer calls concatenate VAD regions and can drift on repeated speech.
CHUNK_SECONDS = 25
CONTEXT_SECONDS = 2
SAMPLE_RATE = 16000


def decode_audio(source: Path, target: Path):
    import imageio_ffmpeg
    target.parent.mkdir(parents=True, exist_ok=True)
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
               "-vn", "-map", "0:a:0", "-t", str(MAX_DURATION + 1), "-af", "aresample=async=1:first_pts=0",
               "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le", str(target)]
    run = subprocess.run(command, capture_output=True, timeout=1800)
    if run.returncode:
        raise ValueError("音轨无法解码，请检查文件或改用 MP3 / WAV")
    with wave.open(str(target), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
        if not math.isfinite(duration) or not 0 < duration <= MAX_DURATION + .05:
            raise ValueError("音轨须在 2 小时以内")
    return duration


def windows(duration: float, seconds: float = CHUNK_SECONDS):
    if not math.isfinite(duration) or duration <= 0 or seconds <= 0:
        raise ValueError("音频时长与分段长度须为正数")
    for index in range(math.ceil(duration / seconds)):
        start, end = index * seconds, min(duration, (index + 1) * seconds)
        yield index, start, end, max(0, start - CONTEXT_SECONDS), min(duration, end + CONTEXT_SECONDS)


def pcm_window(path: Path, start: float, end: float):
    import numpy as np
    with wave.open(str(path), "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1, 2, SAMPLE_RATE):
            raise ValueError("识别音轨应为 16 kHz 单声道 PCM")
        audio.setpos(min(audio.getnframes(), round(start * SAMPLE_RATE)))
        raw = audio.readframes(max(0, round((end - start) * SAMPLE_RATE)))
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def fingerprint(path: Path, options: dict) -> str:
    digest = hashlib.sha256(json.dumps(options, sort_keys=True, ensure_ascii=False).encode())
    with path.open("rb") as audio:
        for block in iter(lambda: audio.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _number(value, fallback=0.0):
    try:
        value = float(value)
        return value if math.isfinite(value) else fallback
    except (TypeError, ValueError):
        return fallback


def uncovered_intervals(start, end, words, cues=(), minimum=1.2):
    """Return real gaps, never infer missing words from a gap's length."""
    intervals = sorted((max(start, w["start"]), min(end, w["end"]))
                       for w in (words or cues) if w["end"] > start and w["start"] < end)
    cursor = start
    for lo, hi in intervals:
        if lo - cursor >= minimum:
            yield cursor, lo
        cursor = max(cursor, hi)
    if end - cursor >= minimum:
        yield cursor, end


def recover_uncovered(engine, wav, start, end, record, language, progress):
    """Isolate missed music vocals from dominant dialogue; keep results reviewable.

    This is not source separation. It cannot recover a second simultaneous
    subtitle track. Up to two locally detected language candidates are decoded;
    neither screen hotwords nor a requested lyric are used to fill gaps.
    """
    import numpy as np
    recovered, evidence = [], []
    for lo, hi in uncovered_intervals(start, end, record["words"], record["cues"]):
        samples = pcm_window(wav, lo, hi)
        if not len(samples) or float(np.sqrt(np.mean(samples ** 2))) < .003:
            continue  # No extra decoding or hallucinated captions on silence.
        progress(0, f"补识别未覆盖片段 {lo:.1f}–{hi:.1f} 秒")
        def decode(chosen):
            segments, info = engine.transcribe(samples, language=chosen, beam_size=5, temperature=0,
                word_timestamps=True, condition_on_previous_text=False, vad_filter=False)
            items, logprobs, silence = [], [], []
            for segment in segments:
                logprobs.append(_number(getattr(segment, "avg_logprob", -2), -2))
                silence.append(_number(getattr(segment, "no_speech_prob", 1), 1))
                for word in getattr(segment, "words", None) or []:
                    a, b = max(lo, lo + _number(word.start)), min(hi, lo + _number(word.end))
                    text = str(word.word)
                    # Zero-length words at a clip edge are decoder guesses,
                    # not usable timing anchors (e.g. an extra final number).
                    if b - a >= .04 and text.strip():
                        items.append({"word": text, "start": round(a, 3), "end": round(b, 3),
                            "probability": round(_number(getattr(word, "probability", 0)), 4),
                            "background_recovered": True, "language": info.language})
            probabilities = [w["probability"] for w in items]
            credible = sum(p >= .55 for p in probabilities)
            average_log = sum(logprobs) / max(1, len(logprobs))
            valid = (bool(items) and credible >= min(2, len(items)) and average_log >= -1.2
                     and float(np.median(probabilities)) >= .55
                     and not (min(silence or [1]) > .95 and np.mean(probabilities) < .85))
            score = average_log + .25 * float(np.mean(probabilities)) if valid else -math.inf
            return items, info, score
        first, info, score = decode(language)
        candidates = [(first, info.language, score)]
        if language is None:
            alternatives = sorted(getattr(info, "all_language_probs", None) or [], key=lambda item: -item[1])
            alternate = next((code for code, prob in alternatives if code != info.language and prob >= .08), None)
            if alternate:
                other, other_info, other_score = decode(alternate)
                candidates.append((other, other_info.language, other_score))
        chosen, chosen_language, best_score = max(candidates, key=lambda item: item[2])
        if math.isfinite(best_score):
            recovered.extend(chosen)
            evidence.append({"start": round(lo, 3), "end": round(hi, 3), "language": chosen_language,
                "words": len(chosen), "needs_listening": True,
                "candidate_languages": [code for _, code, _ in candidates]})
    record["words"].extend({**w, "owner": True} for w in recovered)
    record["recovery"] = evidence


def recognize(wav: Path, model: str, cache: Path, progress, *, language=None,
              singing=False, recover_gaps=False, hints=None, engine_factory=None, chunk_seconds=CHUNK_SECONDS):
    from .media import whisper_model, write_json
    engine_factory = engine_factory or whisper_model
    with wave.open(str(wav), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
    options = {"schema": 4, "model": model, "language": language, "singing": singing, "recover_gaps": recover_gaps, "temperature": 0,
               "hints": hints or [], "chunk_seconds": chunk_seconds, "context": CONTEXT_SECONDS}
    signature = fingerprint(wav, options)
    folder = wav.parent / ".recognition" / signature
    folder.mkdir(parents=True, exist_ok=True)
    chunks = list(windows(duration, chunk_seconds))
    words, cues, recovery, engine, used_cache, detected = [], [], [], None, 0, None
    for index, start, end, read_start, read_end in chunks:
        stored = folder / f"{index:04d}.json"
        try:
            record = json.loads(stored.read_text("utf-8"))
            if (not isinstance(record, dict) or record.get("signature") != signature
                    or not isinstance(record.get("language"), dict)
                    or not isinstance(record.get("words"), list) or not isinstance(record.get("cues"), list)):
                raise ValueError("incomplete chunk")
            for items, text_key in ((record["words"], "word"), (record["cues"], "text")):
                for item in items:
                    if not isinstance(item, dict) or not isinstance(item.get(text_key), str):
                        raise ValueError("invalid chunk text")
                    if any(isinstance(item.get(key), bool) or not isinstance(item.get(key), (int, float))
                           or not math.isfinite(item[key]) for key in ("start", "end")):
                        raise ValueError("invalid chunk time")
                    if not read_start - .01 <= item["start"] <= item["end"] <= read_end + .01:
                        raise ValueError("chunk time outside its window")
            used_cache += 1
        except (OSError, ValueError, TypeError):
            if engine is None:
                progress(0, f"加载 {model} 语音模型；首次使用需下载")
                engine = engine_factory(model, str(cache / "models"))
            segments, info = engine.transcribe(pcm_window(wav, read_start, read_end),
                language=language or (detected or {}).get("language"), beam_size=5, temperature=0,
                word_timestamps=True, condition_on_previous_text=False, vad_filter=not singing,
                hotwords=", ".join(hints or []) or None)
            record = {"signature": signature, "words": [], "cues": [],
                      "language": {"language": info.language,
                                   "language_probability": _number(getattr(info, "language_probability", 0))}}
            for segment in segments:
                owned = []
                for word in getattr(segment, "words", None) or []:
                    lo, hi = read_start + _number(word.start), read_start + _number(word.end)
                    midpoint = (lo + hi) / 2
                    if not read_start <= midpoint < read_end or hi < lo or lo >= duration:
                        continue
                    item = {"word": str(word.word), "start": round(max(0, lo), 3),
                            "end": round(min(duration, hi), 3),
                            "probability": round(_number(getattr(word, "probability", 1)), 4),
                            "owner": start <= midpoint < end}
                    owned.append(item)
                record["words"].extend(owned)
                lo = max(start, read_start + _number(getattr(segment, "start", 0)))
                hi = min(end, read_start + _number(segment.end))
                text = "".join(w["word"] for w in owned if w["owner"]).strip() if getattr(segment, "words", None) else str(getattr(segment, "text", "")).strip()
                if text and hi > lo:
                    record["cues"].append({"text": text, "start": round(lo, 3), "end": round(hi, 3),
                        "no_speech_prob": _number(getattr(segment, "no_speech_prob", 0)),
                        "avg_logprob": _number(getattr(segment, "avg_logprob", 0))})
                position = max(start, min(end, read_start + _number(segment.end)))
                fraction = .8 if recover_gaps else 1
                progress((start + fraction * (position - start)) / duration,
                         f"识别 {index + 1}/{len(chunks)} 段 · {min(end, read_start + _number(segment.end)):.0f}/{duration:.0f} 秒")
            if recover_gaps:
                recover_uncovered(engine, wav, start, end, record, language,
                                  lambda _, message: progress((start + .8 * (end - start)) / duration, message))
            write_json(stored, record)
        detected = detected or record["language"]
        words.extend(record["words"])
        cues.extend(record["cues"])
        recovery.extend(record.get("recovery", []))
        progress(end / duration, f"已完成 {index + 1}/{len(chunks)} 段" + (" · 复用已识别片段" if used_cache else ""))
    # Context windows can timestamp the same boundary word a little differently.
    def same_token(a, b):
        return re.sub(r"[^\w]", "", a["word"].casefold()) == re.sub(r"[^\w]", "", b["word"].casefold())
    def common_time(a, b):
        common = min(a["end"], b["end"]) - max(a["start"], b["start"])
        shorter = min(a["end"] - a["start"], b["end"] - b["start"])
        return shorter > 0 and common / shorter > .5
    selected = [w for w in words if w.get("owner", True)]
    # Two decodes may put the same word on opposite sides of the seam so that
    # neither owns it. Restore that real context word only into an uncovered
    # interval; never derive a word or timestamp from the gap's length.
    for word in sorted((w for w in words if not w.get("owner", True)), key=lambda w: -w.get("probability", 0)):
        if not any(common_time(word, existing) or (same_token(word, existing) and
                   min(word["end"], existing["end"]) > max(word["start"], existing["start"])) for existing in selected):
            selected.append({**word, "boundary_review": True})
    unique = []
    for word in sorted(selected, key=lambda w: (w["start"], w["end"])):
        if unique and same_token(word, unique[-1]):
            previous = unique[-1]
            common = min(previous["end"], word["end"]) - max(previous["start"], word["start"])
            shorter = min(previous["end"] - previous["start"], word["end"] - word["start"])
            if shorter > 0 and common / shorter > .5:
                continue
        unique.append({k: v for k, v in word.items() if k != "owner"})
    if any(w.get("boundary_review") for w in unique) and cues:
        # Rebuild affected draft segments from the selected real word anchors.
        groups = [[] for _ in cues]
        for word in unique:
            midpoint = (word["start"] + word["end"]) / 2
            distances = [max(c["start"] - midpoint, midpoint - c["end"], 0) for c in cues]
            closest = min(range(len(cues)), key=lambda i: distances[i])
            if distances[closest] <= CONTEXT_SECONDS:
                groups[closest].append(word)
        for cue, group in zip(cues, groups):
            if group:
                cue.update(text="".join(w["word"] for w in group).strip(), start=group[0]["start"], end=group[-1]["end"],
                           boundary_review=any(w.get("boundary_review") for w in group))
    return unique, cues, {"engine": "faster-whisper", "model": model, **(detected or {}),
        "word_timing": True, "vad_filter": not singing, "beam_size": 5, "temperature": 0,
        "chunks": len(chunks), "cached_chunks": used_cache, "chunk_seconds": chunk_seconds,
        "context_seconds": CONTEXT_SECONDS, "screen_hotwords": hints or [],
        "recover_gaps": recover_gaps, "recovery": recovery,
        "recovered_words": sum(bool(w.get("background_recovered")) for w in unique)}


def speech_cues(words: list[dict], fallback: list[dict], duration: float) -> list[dict]:
    groups, group = [], []
    def flush():
        if not group:
            return
        text = "".join(w["word"] for w in group).strip()
        start, end = group[0]["start"], min(duration, group[-1]["end"])
        if text and end > start:
            probabilities = [w.get("probability", 1) for w in group]
            groups.append({"id": len(groups) + 1, "start": start, "end": end, "original": text,
                           "boundary_review": any(w.get("boundary_review") for w in group),
                           "background_recovered": any(w.get("background_recovered") for w in group),
                           "recognition_review": min(probabilities) < .45 or any(
                               w.get("boundary_review") or w.get("background_recovered") for w in group)})
        group.clear()
    def reading_length(text):
        # Latin identifiers are much narrower than Chinese glyphs. Counting
        # PyTorch as seven full-width characters creates orphaned numbers.
        return sum(1 if '\u3400' <= char <= '\u9fff' else .55 for char in text)

    for index, word in enumerate(words):
        if group and bool(word.get("background_recovered")) != bool(group[-1].get("background_recovered")):
            flush()
        content = "".join(w["word"] for w in group)
        cjk = bool(re.search(r"[\u3400-\u9fff]", content + word["word"]))
        number_continues = bool(group and word["start"] - group[-1]["end"] <= .3
                                and re.search(r"\d[.,]?$", content.strip())
                                and re.match(r"^[.,]?\d", word["word"].strip())
                                and (re.search(r"\d[.,]$", content.strip()) or not word["word"].startswith(" ")))
        if group and (word["start"] - group[-1]["end"] > .5 or word["end"] - group[0]["start"] > 5
                      or reading_length(content + word["word"]) > (32 if cjk else 38.5)) and not number_continues:
            flush()
        group.append(word)
        next_text = words[index + 1]["word"].strip() if index + 1 < len(words) else ""
        decimal_dot = bool(re.search(r"\d\.$", word["word"].strip()) and re.match(r"^\d", next_text))
        if re.search(r"[。！？.!?]$", word["word"].strip()) and not decimal_dot and word["end"] - group[0]["start"] > .8:
            flush()
    flush()
    if not groups:
        groups = [{"id": i, "start": c["start"], "end": c["end"], "original": c["text"],
                   "recognition_review": c.get("no_speech_prob", 0) > .6 or c.get("avg_logprob", 0) < -1}
                  for i, c in enumerate(fallback, 1)]
    for left, right in zip(groups, groups[1:]):
        if right["start"] < left["end"]:
            left["end"] = right["start"]
    return [c for c in groups if c["end"] > c["start"]]
