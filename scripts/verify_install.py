"""Exercise a public source ZIP in a fresh folder on this machine, not a new PC."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    parent = ROOT / ".cache" / "release-tests"
    parent.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="fresh-", dir=parent)) / "首次安装 with spaces"
    directory.mkdir()
    with zipfile.ZipFile(args.source) as archive:
        for name in archive.namelist():
            if not (directory / name).resolve().is_relative_to(directory.resolve()):
                raise ValueError("Archive path escapes the verification directory")
        archive.extractall(directory)
    project = directory / "muzhun"
    python = project / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    log = directory / "verification.log"

    def command(arguments):
        completed = subprocess.run([str(item) for item in arguments], cwd=project,
                                   capture_output=True, env={**os.environ, "PYTHONUTF8": "1"}, timeout=600)
        with log.open("ab") as stream:
            stream.write(completed.stdout + completed.stderr)
        if completed.returncode:
            raise RuntimeError(f"Command failed ({completed.returncode}); see {log}")
        return completed.stdout.decode("utf-8-sig", "replace")

    base_python = Path(sys.base_prefix) / ("python.exe" if os.name == "nt" else "bin/python3")
    if not base_python.is_file():
        base_python = Path(sys.executable)
    print("Installing from a fresh source folder; logs stay in .cache/release-tests.", flush=True)
    skill = directory / "skills/muzhun-subtitles"
    runtime_record = directory / "runtime.json"
    install_command = [base_python, project / "scripts/setup.py", "--agent", "deepseek",
                       "--destination", skill, "--runtime-record", runtime_record]
    command(install_command)
    print("Fresh environment installed. Checking native libraries and missing model cache.", flush=True)
    report = json.loads(command([python, "-m", "muzhun.cli", "doctor", "--full"]))
    assert report["ready"] and not report["models_cached"], report
    second = command(install_command)
    assert "Installing Muzhun dependencies" not in second, second
    runtime = json.loads(runtime_record.read_text("utf-8"))
    assert Path(runtime["root"]).resolve() == project.resolve(), runtime
    assert Path(runtime["python"]).resolve() == python.resolve(), runtime
    result = json.loads(command([python, skill / "scripts/run.py", "deliver", project / "examples/dynamic-demo.mp4",
                                 "--srt", project / "examples/dynamic-input.srt", "--out", project / "outputs/fresh-delivery",
                                 "--synthetic-demo"]))
    video = Path(result["delivery"]["video"])
    assert video.is_file() and video.stat().st_size > 0, result
    lyrics_text = project / "outputs/lyrics-smoke.lrc"
    lyrics_text.write_text("[00:02.00]" + (project / "examples/lyrics-demo.txt").read_text("utf-8").splitlines()[0] + "\n", "utf-8")
    lyrics = json.loads(command([python, skill / "scripts/run.py", "lyrics", project / "examples/lyrics-demo.wav",
                                  "--text", lyrics_text, "--out", project / "outputs/fresh-lyrics"]))
    lrc = Path(lyrics["lrc"])
    assert lrc.is_file() and lyrics["summary"]["exportable"], lyrics
    summary = {"scope": "fresh-source-folder-on-same-Windows-machine" if os.name == "nt" else "fresh-source-folder-on-same-machine",
               "version": report["version"], "ready": report["ready"], "models_cached": report["models_cached"],
               "second_start_reinstalls": False, "unified_setup": True, "skill_agent": "deepseek", "skill_delivery": True,
               "lyrics_export": True, "lyrics_bytes": lrc.stat().st_size, "video_bytes": video.stat().st_size,
               "work_dir": str(directory), "log": str(log)}
    (ROOT / ".cache/release-install-verification.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
