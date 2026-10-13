"""Read only the requested PCM interval to display an editable waveform."""
from __future__ import annotations

import math
import wave
from pathlib import Path


def envelope(path: Path, start: float = 0, end: float = 30, points: int = 1200):
    import numpy as np
    if not all(math.isfinite(v) for v in (start, end)) or start < 0 or end <= start or end - start > 120:
        raise ValueError("波形窗口须为 0–120 秒的有效时间范围")
    if isinstance(points, bool) or not 50 <= points <= 4000:
        raise ValueError("波形采样点须为 50–4000")
    with wave.open(str(path), "rb") as source:
        if source.getsampwidth() != 2 or source.getnchannels() != 1:
            raise ValueError("波形需要单声道 PCM 音轨")
        rate, duration = source.getframerate(), source.getnframes() / source.getframerate()
        if start >= duration:
            raise ValueError("波形窗口超出音频长度")
        end = min(end, duration)
        source.setpos(round(start * rate))
        samples = np.frombuffer(source.readframes(round((end - start) * rate)), np.int16).astype(np.int32)
    bins = min(points, len(samples))
    if not bins:
        return {"start": start, "end": end, "peaks": []}
    edges = np.linspace(0, len(samples), bins + 1, dtype=int)
    peaks = [int(np.max(np.abs(samples[edges[i]:edges[i + 1]]))) for i in range(bins)]
    scale = max(1, max(peaks))
    return {"start": round(start, 3), "end": round(end, 3),
            "peaks": [round(value / scale, 4) for value in peaks]}
