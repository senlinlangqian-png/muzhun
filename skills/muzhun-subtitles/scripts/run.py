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
            if python.is_file() and root.is_dir():
                return python, root
        except (OSError, ValueError, KeyError, TypeError):
            pass
    for root in Path(__file__).resolve().parents:
        if (root / "pyproject.toml").is_file() and (root / "src" / "muzhun").is_dir():
            for candidate in (root / ".venv" / "Scripts" / "python.exe", root / ".venv" / "bin" / "python"):
                if candidate.is_file():
                    return candidate, root
    raise RuntimeError("Muzhun runtime not found. Install the repository environment or set MUZHUN_HOME; see references/cli.md.")


def main() -> int:
    try:
        python, root = find_runtime()
        return subprocess.call([str(python), "-m", "muzhun.cli", *sys.argv[1:]], cwd=root)
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
