from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def default_root() -> Path:
    configured = os.environ.get("MUZHUN_HOME")
    if configured:
        return Path(configured).resolve()
    project = Path(__file__).resolve().parents[2]
    return project if (project / "pyproject.toml").is_file() else Path.home() / ".muzhun"


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("字幕或词表编码无法读取，请保存为 UTF-8")


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="muzhun", description="幕准：参考画面校正术语，保护正在讲解的内容")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="启动本地可视化工具")
    serve.add_argument("--port", type=int, default=8770)
    serve.add_argument("--open-browser", action="store_true", help="服务就绪后打开浏览器")
    doctor = commands.add_parser("doctor", help="检查运行环境，不下载模型")
    doctor.add_argument("--full", action="store_true", help="同时实际加载识别引擎")
    prepare = commands.add_parser("prepare", help="预下载本地语音模型并检查 OCR")
    prepare.add_argument("--model", default="base", choices=["tiny", "base", "small", "medium", "large-v3-turbo"])
    for command, help_text in (("process", "处理视频，可提供已有 SRT"), ("deliver", "一条命令处理、渲染并生成完整交付包")):
        process_cmd = commands.add_parser(command, help=help_text)
        process_cmd.add_argument("video", type=Path)
        process_cmd.add_argument("--srt", type=Path)
        process_cmd.add_argument("--out", type=Path, required=True)
        process_cmd.add_argument("--profile", default="auto", choices=["auto", "general", "ai-code", "cs2", "valorant"])
        process_cmd.add_argument("--style", default="professional", choices=["professional", "gaming", "minimal"])
        process_cmd.add_argument("--position-policy", default="adaptive", choices=["adaptive", "static"], help="C 模式随画面分时避让，或每句固定一个位置")
        process_cmd.add_argument("--glossary", type=Path)
        process_cmd.add_argument("--model", default="small", choices=["tiny", "base", "small", "medium", "large-v3-turbo"])
        process_cmd.add_argument("--language", default="auto", choices=["auto", "zh", "en", "ja", "ko", "es", "fr", "de", "ru"])
        process_cmd.add_argument("--script", default="auto", choices=["auto", "original", "simplified"])
        process_cmd.add_argument("--synthetic-demo", action="store_true", help="明确标记合成演示素材，不计为真实评测")
    render = commands.add_parser("render", help="导出带字幕视频")
    render.add_argument("report", type=Path)
    render.add_argument("--mode", default="C", choices=["A", "B", "C"])
    render.add_argument("--video", type=Path)
    package = commands.add_parser("package", help="复用已有处理记录，渲染并打包视频、字幕与复核页")
    package.add_argument("report", type=Path)
    package.add_argument("--mode", default="C", choices=["A", "B", "C"])
    package.add_argument("--video", type=Path)
    review = commands.add_parser("revise", help="根据 JSON 修改设置与字幕，再生成布局")
    review.add_argument("report", type=Path)
    review.add_argument("--edits", type=Path, required=True)
    replace_cmd = commands.add_parser("replace", help="预览或应用批量术语替换；默认只预览")
    replace_cmd.add_argument("report", type=Path)
    replace_cmd.add_argument("--find", required=True)
    replace_cmd.add_argument("--replace", required=True)
    replace_cmd.add_argument("--ids", type=int, nargs="+", help="只替换这些字幕编号；默认所有字幕")
    replace_cmd.add_argument("--ignore-case", action="store_true")
    replace_cmd.add_argument("--substring", action="store_true", help="允许匹配拉丁标识符的内部")
    replace_cmd.add_argument("--apply", action="store_true", help="确认预览后应用替换并重新排版")
    replace_cmd.add_argument("--revision", type=int, help="应用时核对预览的修订号，避免覆盖新修改")
    mark = commands.add_parser("review", help="查看逐句复核清单，或标记已经人工核查的 C 字幕")
    mark.add_argument("report", type=Path)
    mark.add_argument("--ids", type=int, nargs="+", help="已经听音并检查画面的字幕编号")
    mark.add_argument("--unmark", action="store_true")
    mark.add_argument("--revision", type=int)
    for command in ("undo", "redo"):
        travel = commands.add_parser(command, help="撤销或重做最近修改，包含文字、时间、布局和复核状态")
        travel.add_argument("report", type=Path)
        travel.add_argument("--revision", type=int)
    evaluate_cmd = commands.add_parser("evaluate", help="使用独立人工标注评测")
    evaluate_cmd.add_argument("report", type=Path)
    evaluate_cmd.add_argument("--annotations", type=Path, required=True)
    blind = commands.add_parser("blind-pack", help="生成随机匿名的三组视频与评分表")
    blind.add_argument("report", type=Path)
    blind.add_argument("--video", type=Path)
    inspect = commands.add_parser("inspect", help="提取真实画面、时间与 OCR 供代理核查")
    inspect.add_argument("video", type=Path)
    inspect.add_argument("--out", type=Path, required=True)
    lyrics = commands.add_parser("lyrics", help="音频转 LRC；可用提供的歌词辅助对齐，或导入已有 LRC/SRT")
    lyrics.add_argument("audio", type=Path)
    lyrics.add_argument("--text", type=Path, help="UTF-8 / GB18030 歌词 TXT、已有 LRC 或 SRT；留空则自动转录")
    lyrics.add_argument("--out", type=Path, required=True)
    lyrics.add_argument("--model", default="small", choices=["tiny", "base", "small", "medium", "large-v3-turbo"])
    lyrics.add_argument("--language", choices=["zh", "en", "ja", "ko", "es", "fr", "de", "ru"])
    lyrics.add_argument("--content", default="song", choices=["song", "speech"])
    lyrics.add_argument("--glossary", type=Path)
    lyrics.add_argument("--script", choices=["auto", "original", "simplified"], default="auto",
                        help="自动转录的中文字形：auto 对中文输出简体；提供的歌词始终保留原文")
    lyrics_align = commands.add_parser("lyrics-align", help="用已保存的音频锚点按新歌词重新对齐，不重跑识别")
    lyrics_align.add_argument("report", type=Path)
    lyrics_align.add_argument("--text", type=Path, required=True)
    lyrics_align.add_argument("--revision", type=int, required=True)
    lyrics_edit = commands.add_parser("lyrics-revise", help="修改歌词时间、文字或复核标记；可撤销 / 重做")
    lyrics_edit.add_argument("report", type=Path)
    lyrics_edit.add_argument("--edits", type=Path, required=True)
    args = parser.parse_args(argv)
    root = default_root()
    cache = root / ".cache"
    progress = lambda value, message: print(f"[{round(value * 100):3d}%] {message}", file=sys.stderr, flush=True)
    try:
        if args.command == "serve":
            from .server import create_app
            from .startup import serve as serve_local
            serve_local(create_app(root), args.port, args.open_browser)
            return 0
        if args.command == "doctor":
            from .diagnostics import runtime_report
            report = runtime_report(root, args.full)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["ready"] else 1
        if args.command == "prepare":
            from .media import ocr_engine, whisper_model
            ocr_engine()
            whisper_model(args.model, str(cache / "models"))
            print(json.dumps({"ready": True, "model": args.model}, ensure_ascii=False))
            return 0
        if args.command in {"lyrics", "lyrics-revise", "lyrics-align"}:
            from .lyrics import process_lyrics, revise_lyrics, save_lyrics
            from .media import read_json
            if args.command == "lyrics":
                output = args.out.resolve()
                result = process_lyrics(args.audio.resolve(), output, read_text(args.text) if args.text else "",
                                        args.model, cache, args.language, progress, args.script, args.content, read_text(args.glossary) if args.glossary else "")
            else:
                output = args.report.resolve().parent
                payload = {"action": "realign", "lyrics": read_text(args.text), "revision": args.revision} if args.command == "lyrics-align" else json.loads(read_text(args.edits))
                result = revise_lyrics(read_json(args.report), payload)
                save_lyrics(result, output)
            response = {"report": str(output / "lyrics-result.json"), "revision": result["revision"],
                        "text_source": result["text_source"], "summary": result["summary"]}
            if result["summary"]["exportable"]:
                response.update(lrc=str(output / "lyrics.lrc"), srt=str(output / "lyrics.srt"))
            print(json.dumps(response, ensure_ascii=False))
            return 0
        from .media import burn_video, extract_frames, probe, read_json, recognize_frames, write_json
        from .pipeline import process, replan, save_exports
        from .evaluation import annotation_template, blind_pack, evaluate
        from .delivery import delivery_pack
        from .editing import mark_review, refresh_review, replacement_preview, replace_result, revise_result, travel_history
        if args.command in {"process", "deliver"}:
            output = args.out.resolve()
            result = process(args.video.resolve(), output, {"profile": args.profile, "style": args.style,
                             "position_policy": args.position_policy, "language": args.language, "script": args.script,
                             "glossary": read_text(args.glossary) if args.glossary else ""},
                             read_text(args.srt) if args.srt else None, args.model, cache, progress)
            result["source_video"] = str(args.video.resolve())
            result["demo"] = args.synthetic_demo
            save_exports(result, output)
            write_json(output / "annotations-template.json", annotation_template(result))
            response = {"report": str(output / "result.json"), "profile": result["profile"], "summary": result["summary"]}
            if args.command == "deliver":
                response["delivery"] = delivery_pack(result, output, args.video.resolve(), progress=progress)
            print(json.dumps(response, ensure_ascii=False))
            return 0
        if args.command == "inspect":
            args.out.mkdir(parents=True, exist_ok=True)
            metadata = probe(args.video)
            frames = extract_frames(args.video, args.out, metadata, progress)
            recognize_frames(frames, args.out, progress)
            write_json(args.out / "frames.json", {"metadata": metadata, "frames": frames})
            print(json.dumps({"report": str(args.out.resolve() / "frames.json"), "frame_count": len(frames)}, ensure_ascii=False))
            return 0
        result = read_json(args.report)
        output = args.report.resolve().parent
        if args.command == "revise":
            payload = json.loads(args.edits.read_text("utf-8"))
            result = revise_result(result, payload)
            save_exports(result, output)
            print(json.dumps({"report": str(args.report), "revision": result["revision"], "summary": result["summary"]}, ensure_ascii=False))
            return 0
        if args.command == "replace":
            payload = {"find": args.find, "replace": args.replace, "ids": args.ids,
                       "case_sensitive": not args.ignore_case, "whole_word": not args.substring, "revision": args.revision}
            preview = replacement_preview(result, payload, limit=None)
            if args.apply:
                result = replace_result(result, payload)
                save_exports(result, output)
            print(json.dumps({**preview, "applied": args.apply, "revision": result.get("revision", 0)}, ensure_ascii=False))
            return 0
        if args.command == "review":
            result = refresh_review(result)
            if args.ids:
                result = mark_review(result, {"ids": args.ids, "reviewed": not args.unmark, "revision": args.revision})
                write_json(output / "result.json", result)
            print(json.dumps({"revision": result["revision"], "summary": result["summary"],
                             "cues": [{key: c[key] for key in ("id", "start", "end", "text", "pending", "layout_review", "reviewed")}
                                      for c in result["cues"]]}, ensure_ascii=False))
            return 0
        if args.command in {"undo", "redo"}:
            result = travel_history(result, {"action": args.command, "revision": args.revision})
            save_exports(result, output)
            print(json.dumps({"report": str(args.report), "revision": result["revision"], "summary": result["summary"], "history": result["history"]}, ensure_ascii=False))
            return 0
        if args.command == "evaluate":
            scores = evaluate(result, json.loads(args.annotations.read_text("utf-8")))
            write_json(output / "evaluation.json", scores)
            print(json.dumps(scores, ensure_ascii=False, indent=2))
            return 0
        video = args.video or Path(result.get("source_video", str(output / result["metadata"]["filename"])))
        if args.command == "package":
            print(json.dumps(delivery_pack(result, output, video, args.mode, progress), ensure_ascii=False))
            return 0
        result = replan(result)
        save_exports(result, output)
        if args.command == "render":
            target = output / f"video-{args.mode}.mp4"
            burn_video(video, output / f"subtitles-{args.mode}.ass", target, progress)
        else:
            target = blind_pack(result, output, video, progress)
        print(json.dumps({"output": str(target.resolve())}, ensure_ascii=False))
        return 0
    except Exception as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
