"""Check public archives and write checksums; this does not publish anything."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text("utf-8"), re.M).group(1)


def check_archive(path: Path, required: set[str]) -> dict:
    with zipfile.ZipFile(path) as archive:
        if archive.testzip():
            raise ValueError(f"Corrupt ZIP: {path.name}")
        names = set(archive.namelist())
        if required - names:
            raise ValueError(f"Missing public files in {path.name}: {sorted(required - names)}")
        for name in names:
            entry = PurePosixPath(name)
            if entry.is_absolute() or ".." in entry.parts or "\\" in name:
                raise ValueError(f"Unsafe archive entry: {name}")
            if any(part in {".venv", ".cache", "outputs", "__pycache__", ".git"} for part in entry.parts):
                raise ValueError(f"Private/generated entry: {name}")
            if entry.name in {"runtime.json", ".env", "blind-key.json"}:
                raise ValueError(f"Local-only entry: {name}")
            if entry.suffix in {".md", ".json", ".toml", ".ps1", ".py", ".yaml", ".yml", ".js", ".html", ".css"}:
                contents = archive.read(name).decode("utf-8-sig")
                private_paths = (str(ROOT), str(ROOT).replace("\\", "\\\\"), ROOT.as_posix())
                if any(value in contents for value in private_paths):
                    raise ValueError(f"Local workspace path leaked: {name}")
        return {"name": path.name, "files": len(names), "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def check(dist: Path) -> list[dict]:
    source = check_archive(dist / f"muzhun-{VERSION}-source.zip", {
        "muzhun/LICENSE", "muzhun/README.md", "muzhun/Start-Muzhun.cmd", "muzhun/run.sh",
        "muzhun/scripts/launch.py", "muzhun/scripts/install_skill.py", "muzhun/docs/quickstart.md",
        "muzhun/docs/release-0.7.md", "muzhun/skills/muzhun-subtitles/SKILL.md", "muzhun/docs/friend-test.md",
        "muzhun/examples/dynamic-demo.mp4", "muzhun/src/muzhun/diagnostics.py",
        "muzhun/src/muzhun/editing.py", "muzhun/tests/test_v05.py", "muzhun/docs/v05-editor-preview.jpg",
        "muzhun/src/muzhun/lyrics.py", "muzhun/src/muzhun/lyrics_web.py", "muzhun/tests/test_v06.py",
        "muzhun/src/muzhun/web/lyrics.html", "muzhun/examples/lyrics-demo.wav",
        "muzhun/tests/test_v07.py", "muzhun/docs/v07-lyrics-preview.jpg",
        "muzhun/.github/ISSUE_TEMPLATE/bug_report.yml", "muzhun/.github/ISSUE_TEMPLATE/feature_request.yml",
        "muzhun/.github/ISSUE_TEMPLATE/question.yml",
    })
    with zipfile.ZipFile(dist / source["name"]) as archive:
        batches = [sum(not item.filename.startswith("muzhun/docs/") for item in archive.infolist()),
                   sum(item.filename.startswith("muzhun/docs/") for item in archive.infolist())]
        if any(count > 100 for count in batches) or any(item.file_size > 25 * 1024 * 1024 for item in archive.infolist()):
            raise ValueError("Source no longer fits the documented two-batch GitHub upload")
    skill = check_archive(dist / f"muzhun-subtitles-skill-{VERSION}.zip", {
        "muzhun-subtitles/SKILL.md", "muzhun-subtitles/scripts/run.py", "muzhun-subtitles/references/cli.md",
    })
    wheel_path = dist / f"muzhun-{VERSION}-py3-none-any.whl"
    wheel = check_archive(wheel_path, {"muzhun/web/index.html", "muzhun/web/app.js",
                         "muzhun/data/profiles.json", "muzhun/diagnostics.py", "muzhun/startup.py", "muzhun/editing.py",
                         "muzhun/lyrics.py", "muzhun/lyrics_web.py", "muzhun/web/lyrics.html", "muzhun/web/lyrics.js"})
    with zipfile.ZipFile(wheel_path) as archive:
        metadata = archive.read(f"muzhun-{VERSION}.dist-info/METADATA").decode()
        if f"Version: {VERSION}" not in metadata.splitlines():
            raise ValueError("Wheel metadata has a different version")
        source_files = {path.relative_to(ROOT / "src").as_posix(): path for path in (ROOT / "src" / "muzhun").rglob("*")
                        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"}
        packaged_files = {name for name in archive.namelist() if name.startswith("muzhun/")}
        if packaged_files != set(source_files):
            raise ValueError("Wheel has missing or obsolete package resources")
        for name, path in source_files.items():
            if archive.read(name) != path.read_bytes():
                raise ValueError(f"Wheel does not contain current source: {name}")
    artifacts = [source, skill, wheel]
    (dist / "SHA256SUMS.txt").write_text("".join(f"{item['sha256']}  {item['name']}\n" for item in artifacts), "utf-8")
    (dist / f"muzhun-{VERSION}-artifacts.json").write_text(json.dumps({"version": VERSION, "artifacts": artifacts}, ensure_ascii=False, indent=2), "utf-8")
    return artifacts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    print(json.dumps({"version": VERSION, "archives_checked": check(args.dist)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
