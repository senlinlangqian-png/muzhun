"""Local audio/lyrics endpoints, sharing the video app's worker and token."""
from __future__ import annotations

import re
import secrets
import threading
import time
from pathlib import Path

from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from .editing import StaleRevision
from .lyrics import MODELS, process_lyrics, revise_lyrics, save_lyrics
from .media import read_json, write_json
from .limits import LANGUAGES, MAX_AUDIO_BYTES, MAX_TEXT_CHARS

AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".aac", ".mp4", ".webm"}


def register_lyrics(app, root: Path, pool, authenticate):
    output = root / "outputs" / "lyrics"
    output.mkdir(parents=True, exist_ok=True)
    active, locks = set(), {}

    def folder_for(job_id):
        if not re.fullmatch(r"[a-f0-9]{16}", job_id) or not (output / job_id).is_dir():
            raise HTTPException(404, "歌词任务不存在")
        return output / job_id

    def status_for(job_id):
        folder = folder_for(job_id)
        current = read_json(folder / "state.json")
        if current["status"] in {"queued", "running"} and job_id not in active:
            current.update(status="error", message="上次处理已中断，可重试并复用已完成片段")
        return current

    def submit(job_id, source, state):
        active.add(job_id)
        def progress(value, message):
            state.update(progress=round(value, 3), message=message)
            write_json(source.parent / "state.json", state)
        def run():
            try:
                state.update(status="running")
                write_json(source.parent / "state.json", state)
                options = state["request"]
                process_lyrics(source, source.parent, options["lyrics"], options["model"], root / ".cache",
                               None if options["language"] == "auto" else options["language"], progress, options["script"], options.get("content", "song"), options.get("glossary", ""))
                state.update(status="ready", progress=1, message="请试听并核对文字与时间")
            except Exception as error:
                state.update(status="error", message=str(error))
            finally:
                write_json(source.parent / "state.json", state)
                active.discard(job_id)
        pool.submit(run)

    @app.get("/api/lyrics")
    def recent():
        entries = []
        for path in sorted(output.glob("*/state.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
            try:
                current = dict(status_for(path.parent.name))
                current.pop("request", None)
                entries.append(current)
            except (HTTPException, OSError, ValueError, KeyError):
                continue
        return entries

    @app.post("/api/lyrics/{job_id}/retry")
    def retry_job(job_id: str, request: Request):
        authenticate(request)
        with locks.setdefault(job_id, threading.Lock()):
            state = status_for(job_id)
            if state["status"] != "error" or not state.get("request"):
                raise HTTPException(409, "仅可重试当前版本中处理失败的音频任务")
            source = next((p for p in folder_for(job_id).glob("source.*") if p.suffix.lower() in AUDIO_SUFFIXES), None)
            if source is None:
                raise HTTPException(404, "原音频已不存在，请重新上传")
            state.update(status="queued", progress=0, message="重试中，将复用已完成的识别片段")
            write_json(source.parent / "state.json", state)
            submit(job_id, source, state)
        return {"id": job_id}

    @app.get("/api/lyrics/{job_id}/waveform")
    def waveform(job_id: str, start: float = 0, end: float = 30, points: int = 1200):
        from .waveform import envelope
        wav = folder_for(job_id) / "audio.wav"
        if not wav.is_file():
            return {"start": start, "end": end, "peaks": []}
        try:
            return envelope(wav, start, end, points)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @app.get("/lyrics")
    def page():
        return FileResponse(Path(__file__).parent / "web" / "lyrics.html")

    @app.post("/api/lyrics")
    async def upload(request: Request, audio: UploadFile = File(...), lyrics: str = Form(""),
                     model: str = Form("small"), language: str = Form("auto"), script: str = Form("auto"),
                     content: str = Form("song"), glossary: str = Form("")):
        authenticate(request)
        suffix = Path(audio.filename or "").suffix.lower()
        if suffix not in AUDIO_SUFFIXES or model not in MODELS or language not in LANGUAGES or script not in {"auto", "original", "simplified"}:
            raise HTTPException(400, "音频格式、模型或语言选项无效")
        if content not in {"song", "speech"} or len(glossary) > MAX_TEXT_CHARS:
            raise HTTPException(400, "音频类型或术语表无效")
        if len(lyrics) > MAX_TEXT_CHARS:
            raise HTTPException(400, "歌词过长，请分段处理")
        job_id = secrets.token_hex(8)
        folder = output / job_id
        folder.mkdir()
        source = folder / ("source" + suffix)
        size = 0
        try:
            with source.open("wb") as target:
                while chunk := await audio.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_AUDIO_BYTES:
                        raise HTTPException(413, "音频最大 512 MB")
                    target.write(chunk)
        finally:
            await audio.close()
        state = {"id": job_id, "name": (audio.filename or "音频")[:120], "status": "queued",
                 "progress": 0, "message": "等待处理", "created_at": time.time(),
                 "request": {"lyrics": lyrics, "model": model, "language": language, "script": script, "content": content, "glossary": glossary}}
        write_json(folder / "state.json", state)
        submit(job_id, source, state)
        return {"id": job_id}

    @app.get("/api/lyrics/{job_id}")
    def get_job(job_id: str):
        state = status_for(job_id)
        if state["status"] == "ready":
            folder = folder_for(job_id)
            state["result"] = read_json(folder / "lyrics-result.json")
            playable = "audio.wav" if (folder / "audio.wav").is_file() else Path(state["result"]["source_audio"]).name
            state["audio_url"] = f"/api/lyrics/{job_id}/files/{playable}"
        return state

    @app.post("/api/lyrics/{job_id}/revise")
    def revise(job_id: str, request: Request, payload: dict):
        authenticate(request)
        with locks.setdefault(job_id, threading.Lock()):
            if status_for(job_id)["status"] != "ready":
                raise HTTPException(409, "请等待音频处理完成")
            folder = folder_for(job_id)
            try:
                result = revise_lyrics(read_json(folder / "lyrics-result.json"), payload)
                save_lyrics(result, folder)
                return result
            except StaleRevision as error:
                raise HTTPException(409, str(error)) from error
            except (ValueError, TypeError, KeyError) as error:
                raise HTTPException(400, str(error)) from error

    @app.get("/api/lyrics/{job_id}/files/{filename}")
    def file(job_id: str, filename: str, revision: int | None = None):
        folder = folder_for(job_id)
        target = (folder / filename).resolve()
        allowed = {"lyrics.lrc", "lyrics.srt", "lyrics-result.json", "audio.wav"}
        if filename not in allowed and not (filename.startswith("source.") and Path(filename).suffix in AUDIO_SUFFIXES):
            raise HTTPException(404, "文件不存在")
        if not target.is_relative_to(folder.resolve()) or not target.is_file():
            raise HTTPException(404, "文件尚未生成，请先补齐未定位歌词")
        if filename in {"lyrics.lrc", "lyrics.srt", "lyrics-result.json"}:
            with locks.setdefault(job_id, threading.Lock()):
                result = read_json(folder / "lyrics-result.json")
                if revision is not None and result["revision"] != revision:
                    raise HTTPException(409, "歌词已更新，请刷新后下载")
                # Read bytes while holding the edit lock: a download belongs to
                # one revision even if another tab immediately saves a change.
                from fastapi.responses import Response
                mime = "application/json" if filename.endswith(".json") else "text/plain; charset=utf-8"
                return Response(target.read_bytes(), media_type=mime, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
        return FileResponse(target)
