"""Portable launcher for the repository runtime or a local install record."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def find_runtime() -> tuple[Path, Path]:
    skill = Path(__file__).resolve().parents[1]
    record = skill / "references" / "runtime.json"
    if os.environ.get("MUZHUN_HOME"):
        root = Path(os.environ["MUZHUN_HOME"]).expanduser().resolve()
        for candidate in (root / ".venv" / "Scripts" / "python.exe", root / ".venv" / "bin" / "python"):
            if candidate.is_file() and (root / "src" / "muzhun").is_dir():
                return candidate, root
        raise RuntimeError("MUZHUN_HOME has no initialized Muzhun environment. Run that project's launcher first.")
    if record.is_file():
        try:
            data = json.loads(record.read_text("utf-8-sig"))
            python = Path(data["python"])
            root = Path(data["root"])
            if python.is_file() and (root / "src/muzhun").is_dir():
                return python, root
        except (OSError, ValueError, KeyError, TypeError):
            pass
    for root in Path(__file__).resolve().parents:
        if (root / "pyproject.toml").is_file() and (root / "src" / "muzhun").is_dir():
            for candidate in (root / ".venv" / "Scripts" / "python.exe", root / ".venv" / "bin" / "python"):
                if candidate.is_file():
                    return candidate, root
    shared = Path.home() / ".muzhun" / "runtime.json"
    if shared.is_file():
        try:
            data = json.loads(shared.read_text("utf-8-sig"))
            root, python = Path(data["root"]), Path(data["python"])
            if python.is_file() and (root / "src/muzhun").is_dir():
                return python, root
        except (OSError, ValueError, KeyError, TypeError):
            pass
    raise RuntimeError("Muzhun runtime not found. Install the repository environment or set MUZHUN_HOME; see references/cli.md.")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        if sys.argv[1:2] == ["setup"]:
            import argparse
            parser = argparse.ArgumentParser(description="从完整源码包安装幕准引擎与 Skill")
            parser.add_argument("--source", type=Path, required=True, help="已解压的幕准项目目录")
            parser.add_argument("--agent", default="codex")
            args = parser.parse_args(sys.argv[2:])
            root = args.source.expanduser().resolve()
            setup = root / "scripts/setup.py"
            if not setup.is_file() or not (root / "src/muzhun").is_dir():
                raise RuntimeError("请将 --source 指向包含 scripts/setup.py 的完整幕准源码目录")
            return subprocess.call([sys.executable, str(setup), "--agent", args.agent], cwd=root)

        python, root = find_runtime()
        return subprocess.call([str(python), "-m", "muzhun.cli", *sys.argv[1:]], cwd=root)
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
