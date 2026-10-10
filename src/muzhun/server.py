from __future__ import annotations

import json
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .cli import read_text
from . import __version__
from .delivery import delivery_pack
from .editing import StaleRevision, check_revision, mark_review, replacement_preview, replace_result, revise_result, travel_history
from .evaluation import annotation_template, blind_pack, evaluate
from .media import burn_video, read_json, write_json
from .pipeline import process, save_exports


def create_app(root: Path) -> FastAPI:
    app = FastAPI(title="幕准", docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    output = root / "outputs"
    output.mkdir(parents=True, exist_ok=True)
    web = Path(__file__).parent / "web"
    jobs = {}
    locks = {}
    token = secrets.token_urlsafe(24)
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="muzhun")

    def authenticate(request: Request):
        if request.headers.get("X-Muzhun-Token") != token:
            raise HTTPException(403, "请从本地页面发起操作")

    def directory(job_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{16}", job_id):
            raise HTTPException(404, "任务不存在")
        folder = output / job_id
        if not folder.is_dir():
            raise HTTPException(404, "任务不存在")
        return folder

    def state(job_id: str) -> dict:
        if job_id not in jobs:
            folder = directory(job_id)
            if (folder / "state.json").exists():
                jobs[job_id] = read_json(folder / "state.json")
                if jobs[job_id]["status"] in {"running", "queued", "exporting"}:
                    jobs[job_id].update(status="error", message="上次运行中断，请重新处理素材")
            else:
                raise HTTPException(404, "任务不存在")
        return jobs[job_id]

    def result_for(job_id: str) -> dict:
        path = directory(job_id) / "result.json"
        if not path.is_file():
            raise HTTPException(409, "视频尚未完成处理")
        return read_json(path)

    def save_state(job_id: str):
        write_json(output / job_id / "state.json", jobs[job_id])

    def progress_for(job_id: str):
        def update(value, message):
            jobs[job_id].update(progress=round(value, 3), message=message)
        return update

    def process_job(job_id: str, video: Path, settings: dict, subtitle: str | None, model: str, demo=False):
        with locks.setdefault(job_id, threading.Lock()):
            jobs[job_id].update(status="running")
            try:
                result = process(video, video.parent, settings, subtitle, model, root / ".cache", progress_for(job_id))
                result.update(source_video=str(video.resolve()), demo=demo)
                save_exports(result, video.parent)
                write_json(video.parent / "annotations-template.json", annotation_template(result))
                jobs[job_id].update(status="ready", progress=1, message="处理完成", error=None)
            except Exception as error:
                jobs[job_id].update(status="error", message=str(error), error=str(error))
            save_state(job_id)

    async def store_upload(upload: UploadFile, path: Path, limit: int):
        total = 0
        with path.open("wb") as file:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > limit:
                    raise HTTPException(413, "文件过大：视频最多 250 MB，字幕最多 2 MB")
                file.write(chunk)
        await upload.close()

    @app.get("/api/status")
    def status():
        return {"token": token, "version": __version__, "max_duration": 600,
                "demo_available": (root / "examples" / "demo.mp4").is_file(),
                "moving_demo_available": (root / "examples" / "dynamic-demo.mp4").is_file()}

    @app.get("/api/health")
    def health():
        return {"app": "muzhun", "version": __version__}

    @app.get("/api/doctor")
    def doctor():
        from .diagnostics import runtime_report
        return runtime_report(root)

    @app.get("/api/jobs")
    def history():
        entries = []
        for path in sorted(output.glob("*/state.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:12]:
            try:
                entries.append(state(path.parent.name))
            except (HTTPException, ValueError):
                continue
        return entries

    @app.post("/api/jobs")
    async def upload(request: Request, video: UploadFile = File(...), subtitle: UploadFile | None = File(None),
                     profile: str = Form("auto"), style: str = Form("professional"), model: str = Form("small"), glossary: str = Form("")):
        authenticate(request)
        if model not in {"tiny", "base", "small", "medium", "large-v3-turbo"}:
            raise HTTPException(400, "不支持的语音模型")
        suffix = Path(video.filename or "").suffix.lower()
        if suffix not in {".mp4", ".mov", ".mkv", ".webm", ".avi"}:
            raise HTTPException(400, "请选择 MP4、MOV、MKV、WebM 或 AVI 视频")
        job_id = secrets.token_hex(8)
        folder = output / job_id
        folder.mkdir()
        source = folder / ("source" + suffix)
        await store_upload(video, source, 250 * 1024 * 1024)
        subtitle_text = None
        if subtitle and subtitle.filename:
            await store_upload(subtitle, folder / "input.srt", 2 * 1024 * 1024)
            subtitle_text = read_text(folder / "input.srt")
        jobs[job_id] = {"id": job_id, "name": (video.filename or "视频")[:120], "status": "queued", "progress": 0,
                        "message": "等待处理", "created_at": time.time(), "demo": False}
        save_state(job_id)
        pool.submit(process_job, job_id, source, {"profile": profile, "style": style, "glossary": glossary}, subtitle_text, model)
        return {"id": job_id}

    @app.post("/api/demo")
    def demo(request: Request, payload: dict | None = None):
        authenticate(request)
        import shutil
        kind = (payload or {}).get("kind", "standard")
        if kind not in {"standard", "moving"}:
            raise HTTPException(400, "不支持的示例类型")
        prefix = "dynamic" if kind == "moving" else "demo"
        demo_video = "dynamic-demo.mp4" if kind == "moving" else "demo.mp4"
        if not (root / "examples" / demo_video).exists():
            raise HTTPException(404, "请先运行对应的 make_demo.py 或 make_dynamic_demo.py 生成合成示例")
        job_id = secrets.token_hex(8)
        folder = output / job_id
        folder.mkdir()
        source = folder / "source.mp4"
        shutil.copyfile(root / "examples" / demo_video, source)
        jobs[job_id] = {"id": job_id, "name": "面板换位示例 · 句内避让" if kind == "moving" else "合成教程示例 · 可控错词", "status": "queued", "progress": 0,
                        "message": "等待处理", "created_at": time.time(), "demo": True}
        save_state(job_id)
        pool.submit(process_job, job_id, source, {"profile": "auto", "style": "professional"},
                    read_text(root / "examples" / f"{prefix}-input.srt"), "base", True)
        return {"id": job_id}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        current = dict(state(job_id))
        if current["status"] in {"ready", "exporting"} and (directory(job_id) / "result.json").is_file():
            current["result"] = result_for(job_id)
            if current.get("export_revision") != current["result"].get("revision", 0):
                current.update(export_url=None, review_url=None, export_kind=None)
        return current

    def mutate(job_id: str, payload: dict, request: Request, operation, review_only=False):
        authenticate(request)
        if state(job_id)["status"] != "ready":
            raise HTTPException(409, "请等待当前处理或导出完成")
        with locks.setdefault(job_id, threading.Lock()):
            if state(job_id)["status"] != "ready":
                raise HTTPException(409, "请等待当前处理或导出完成")
            try:
                before = result_for(job_id)
                result = operation(before, payload)
                if review_only:
                    write_json(directory(job_id) / "result.json", result)
                else:
                    save_exports(result, directory(job_id))
                if result.get("revision", 0) != before.get("revision", 0):
                    jobs[job_id].update(export_url=None, export_kind=None, review_url=None, export_revision=None)
                save_state(job_id)
                return result
            except StaleRevision as error:
                raise HTTPException(409, str(error)) from error
            except (ValueError, TypeError) as error:
                raise HTTPException(400, str(error)) from error

    @app.post("/api/jobs/{job_id}/revise")
    def revise(job_id: str, payload: dict, request: Request):
        return mutate(job_id, payload, request, revise_result)

    @app.post("/api/jobs/{job_id}/review")
    def review(job_id: str, payload: dict, request: Request):
        return mutate(job_id, payload, request, mark_review, review_only=True)

    @app.post("/api/jobs/{job_id}/replace-preview")
    def preview_replace(job_id: str, payload: dict, request: Request):
        authenticate(request)
        try:
            return replacement_preview(result_for(job_id), payload)
        except StaleRevision as error:
            raise HTTPException(409, str(error)) from error
        except (ValueError, TypeError) as error:
            raise HTTPException(400, str(error)) from error

    @app.post("/api/jobs/{job_id}/replace")
    def replace(job_id: str, payload: dict, request: Request):
        return mutate(job_id, payload, request, replace_result)

    @app.post("/api/jobs/{job_id}/history")
    def edit_history(job_id: str, payload: dict, request: Request):
        return mutate(job_id, payload, request, travel_history)

    @app.post("/api/jobs/{job_id}/export")
    def export(job_id: str, payload: dict, request: Request):
        authenticate(request)
        if state(job_id)["status"] != "ready":
            raise HTTPException(409, "请等待当前处理完成")
        mode = payload.get("mode", "C")
        if mode not in {"A", "B", "C", "blind", "delivery"}:
            raise HTTPException(400, "不支持的导出模式")
        variant = payload.get("variant", "C")
        if variant not in {"A", "B", "C"}:
            raise HTTPException(400, "不支持的字幕对比模式")
        with locks.setdefault(job_id, threading.Lock()):
            current = state(job_id)
            if current["status"] != "ready":
                raise HTTPException(409, "请等待当前处理完成")
            # Capture the exact edition under the same lock used by mutations.
            # Errors reading the report occur before setting an exporting state.
            result = result_for(job_id)
            try:
                check_revision(result, payload.get("revision"))
            except StaleRevision as error:
                raise HTTPException(409, str(error)) from error
            edition = result.get("revision", 0)
            current.update(status="exporting", progress=0, message="准备导出", export_url=None,
                           export_kind=None, review_url=None, export_revision=edition, error=None)
            save_state(job_id)
        def run():
            with locks.setdefault(job_id, threading.Lock()):
                try:
                    folder = directory(job_id)
                    video = Path(result["source_video"])
                    save_exports(result, folder)
                    if mode == "blind":
                        target = blind_pack(result, folder, video, progress_for(job_id))
                        batch = target.stem.removeprefix("blind-test-")
                        current["review_url"] = f"/api/jobs/{job_id}/files/friend-test/{batch}/index.html"
                    elif mode == "delivery":
                        packaged = delivery_pack(result, folder, video, variant, progress_for(job_id), edition=edition)
                        target = Path(packaged["output"])
                        current["review_url"] = f"/api/jobs/{job_id}/files/delivery-{variant}-r{edition}/review.html"
                    else:
                        target = folder / f"video-{mode}-r{edition}.mp4"
                        burn_video(video, folder / f"subtitles-{mode}.ass", target, progress_for(job_id))
                    current.update(status="ready", progress=1, message="导出完成", export_kind=mode, export_url=f"/api/jobs/{job_id}/files/{target.name}", error=None)
                except Exception as error:
                    current.update(status="ready", message="导出失败：" + str(error), error=str(error),
                                   export_url=None, review_url=None, export_kind=None)
                save_state(job_id)
        pool.submit(run)
        return {"started": True}

    @app.post("/api/jobs/{job_id}/evaluate")
    def score(job_id: str, payload: dict, request: Request):
        authenticate(request)
        try:
            scores = evaluate(result_for(job_id), payload)
            write_json(directory(job_id) / "evaluation.json", scores)
            return scores
        except (ValueError, KeyError, TypeError) as error:
            raise HTTPException(400, "标注格式无效：" + str(error)) from error

    @app.get("/api/jobs/{job_id}/files/{filename:path}")
    def file(job_id: str, filename: str):
        folder = directory(job_id).resolve()
        target = (folder / filename).resolve()
        if not target.is_relative_to(folder) or not target.is_file() or target.suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm", ".avi", ".jpg", ".json", ".srt", ".ass", ".zip", ".html", ".csv"}:
            raise HTTPException(404, "文件不存在")
        return FileResponse(target, filename=target.name if target.suffix in {".srt", ".ass", ".json", ".zip"} else None)

    from .lyrics_web import register_lyrics
    register_lyrics(app, root, pool, authenticate)

    @app.get("/")
    def index():
        return FileResponse(web / "index.html")

    app.mount("/static", StaticFiles(directory=web), name="static")
    app.state.root = root
    app.state.token = token
    return app
