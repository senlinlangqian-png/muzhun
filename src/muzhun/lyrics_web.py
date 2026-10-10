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
            current.update(status="error", message="上次处理已中断，请重新导入")
        return current

    @app.get("/lyrics")
    def page():
        return FileResponse(Path(__file__).parent / "web" / "lyrics.html")

    @app.post("/api/lyrics")
    async def upload(request: Request, audio: UploadFile = File(...), lyrics: str = Form(""),
                     model: str = Form("small"), language: str = Form("auto"), script: str = Form("auto")):
        authenticate(request)
        suffix = Path(audio.filename or "").suffix.lower()
        if suffix not in AUDIO_SUFFIXES or model not in MODELS or language not in {"auto", "zh", "en", "ja", "ko"} or script not in {"auto", "original", "simplified"}:
            raise HTTPException(400, "音频格式、模型或语言选项无效")
        if len(lyrics) > 30000:
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
                    if size > 250 * 1024 * 1024:
                        raise HTTPException(413, "音频最大 250 MB")
                    target.write(chunk)
        finally:
            await audio.close()
        state = {"id": job_id, "name": (audio.filename or "音频")[:120], "status": "queued",
                 "progress": 0, "message": "等待处理", "created_at": time.time()}
        write_json(folder / "state.json", state)
        active.add(job_id)

        def progress(value, message):
            state.update(progress=round(value, 3), message=message)
            write_json(folder / "state.json", state)

        def run():
            try:
                state.update(status="running")
                write_json(folder / "state.json", state)
                process_lyrics(source, folder, lyrics, model, root / ".cache", None if language == "auto" else language, progress, script)
                state.update(status="ready", progress=1, message="请试听并核对歌词时间")
            except Exception as error:
                state.update(status="error", message=str(error))
            finally:
                write_json(folder / "state.json", state)
                active.discard(job_id)
        pool.submit(run)
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
