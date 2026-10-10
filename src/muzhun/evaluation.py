from __future__ import annotations

import csv
import io
import json
import random
import re
import secrets
import shutil
import zipfile
from pathlib import Path

from .layout import overlap
from .media import burn_video, write_json


def evaluate(result: dict, annotations: dict) -> dict:
    """Evaluate against separately supplied human labels, never inferred anchors."""
    labels = annotations.get("items", [])
    if not labels:
        raise ValueError("评测标注 items 不能为空")
    scores = {}
    for mode, placements in result["plans"].items():
        correct = expected = 0
        blocked = duration = 0.0
        details = []
        for label in labels:
            start, end = float(label["start"]), float(label["end"])
            if end <= start:
                raise ValueError("标注结束时间必须晚于开始时间")
            relevant = [p for p in placements if p["start"] < end and p["end"] > start]
            text = " ".join(p["text"].replace("\n", " ") for p in relevant)
            terms = label.get("terms", [])
            def present(term):
                # Short Latin terms such as API must not match CAPITAL.
                pattern = re.escape(term)
                if re.search(r"[A-Za-z0-9_]", term):
                    pattern = r"(?<![A-Za-z0-9_])" + pattern + r"(?![A-Za-z0-9_])"
                return bool(re.search(pattern, text))
            hits = sum(present(term) for term in terms)
            correct += hits
            expected += len(terms)
            regions = label.get("regions", [])
            # Integrate disjoint time intervals to avoid double-counting overlaps.
            cuts = sorted({start, end, *[max(start, min(end, t)) for p in relevant for t in (p["start"], p["end"])]})
            local_blocked = 0.0
            for left, right in zip(cuts, cuts[1:]):
                middle = (left + right) / 2
                active = [p for p in relevant if p["start"] <= middle < p["end"]]
                if any(overlap(p["rect"], rect) > 0.00001 for p in active for rect in regions):
                    local_blocked += right - left
            if regions:
                duration += end - start
                blocked += local_blocked
            details.append({"start": start, "end": end, "terms_correct": hits, "terms_total": len(terms), "blocked_seconds": round(local_blocked, 3)})
        scores[mode] = {"term_recall": round(correct / expected, 4) if expected else None,
                        "terms_correct": correct, "terms_total": expected,
                        "blocked_seconds": round(blocked, 3), "labeled_seconds": round(duration, 3), "items": details}
    return {"source": "supplied-annotations", "provenance": annotations.get("provenance", "unspecified"), "scores": scores,
            "note": "术语召回不等同于全部字幕准确率；误改和人工修改时间须由测试者记录。"}


def annotation_template(result: dict) -> dict:
    return {"instructions": "由熟悉内容的人填写 terms 和 regions；不要直接把自动绑定当成人工正确答案。矩形为 [左,上,右,下]，范围 0~1。",
            "items": [{"start": cue["start"], "end": cue["end"], "terms": [], "regions": []} for cue in result["cues"]]}


def blind_pack(result: dict, job_dir: Path, video: Path, progress=lambda *_: None) -> Path:
    from .delivery import template_page, verify_render
    from .media import probe
    source = probe(video)
    modes = ["A", "B", "C"]
    random.SystemRandom().shuffle(modes)
    mapping = {name: mode for name, mode in zip(["片段甲", "片段乙", "片段丙"], modes)}
    batch = secrets.token_hex(4)
    key_dir = job_dir / "blind-keys"
    key_dir.mkdir(exist_ok=True)
    latest_key = job_dir / "blind-key.json"
    if latest_key.is_file():
        previous = json.loads(latest_key.read_text("utf-8"))
        previous_batch = str(previous.get("batch", ""))
        if not re.fullmatch(r"[a-f0-9]{8,16}", previous_batch):
            raise ValueError("旧盲测对照表缺少有效批次，请先保存该记录")
        archived = key_dir / f"{previous_batch}.json"
        if not archived.exists():
            write_json(archived, previous)
    assisted = any(bool(edit) for edit in result.get("edits", {}).values()) or bool(result["settings"].get("pins") or result["settings"].get("regions"))
    folder = job_dir / "friend-test" / batch
    folder.mkdir(parents=True)
    for index, mode in enumerate(modes):
        target = job_dir / f"video-{mode}.mp4"
        burn_video(video, job_dir / f"subtitles-{mode}.ass", target,
                   lambda value, message: progress((index + value) / 3, f"盲测包 {index + 1}/3 · {message}"))
        verify_render(source, probe(target))
        shutil.copyfile(target, folder / f"clip-{index + 1}.mp4")
    output = job_dir / f"blind-test-{batch}.zip"
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["批次", "测试者", "熟悉程度", "观看序号", "片段", "错词数量", "误改数量", "遮挡重点秒数", "修改到可发布的分钟数", "清晰度1至5", "愿否处理第二个视频", "备注"])
    for name in mapping:
        writer.writerow([batch, "", "", "", name, "", "", "", "", "", "", ""])
    (folder / "评分表.csv").write_text("\ufeff" + buffer.getvalue(), "utf-8")
    (folder / "index.html").write_text(template_page("blind-review.html", {
        "batch": batch, "demo": result.get("demo", False), "assisted": assisted,
        "clips": [{"name": name, "file": f"clip-{i + 1}.mp4"} for i, name in enumerate(mapping)]}), "utf-8")
    (folder / "测试说明.txt").write_text("请先解压完整文件夹，再双击 index.html。用同一屏幕观看三个匿名片段，熟悉内容的人先确认正确专业词与重点区域。页面随机排列观看顺序；填写后下载评分 CSV 交给作者。没测过的项留空；修改时间应实际计时。页面不会上传数据。模式对照表由作者另存，评分后再揭示。CSV 可用 Excel 打开。\n", "utf-8")
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ["index.html", "评分表.csv", "测试说明.txt", "clip-1.mp4", "clip-2.mp4", "clip-3.mp4"]:
            archive.write(folder / name, name)
    private_key = {"mapping": mapping, "batch": batch, "demo": result.get("demo", False),
                   "assisted": assisted, "note": "仅作者保留，请评分完成后再揭示"}
    write_json(key_dir / f"{batch}.json", private_key)
    write_json(job_dir / "blind-key.json", private_key)
    progress(1.0, "盲测包完成，对照表单独保存")
    return output
