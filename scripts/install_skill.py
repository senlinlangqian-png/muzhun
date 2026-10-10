"""Install this project's skill and a local runtime record on any desktop OS."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skills" / "muzhun-subtitles"
AGENT_ROOTS = {
    "codex": ("CODEX_HOME", ".codex"), "deepseek": ("DSH_HOME", ".dsh"),
    "claude": (None, ".claude"), "cursor": (None, ".cursor"),
    "gemini": (None, ".gemini"), "opencode": (None, ".config/opencode"),
    "kimi": (None, ".kimi"), "agents": ("DSH_AGENTS_HOME", ".agents"),
}


def default_destination(agent: str = "codex") -> Path:
    environment, folder = AGENT_ROOTS[agent]
    home = Path(os.environ.get(environment, str(Path.home() / folder))) if environment else Path.home() / folder
    return home / "skills" / "muzhun-subtitles"


def install(destination: Path, update: bool = False) -> Path:
    destination = destination.expanduser().resolve()
    if destination == SOURCE.resolve() or SOURCE.resolve() in destination.parents:
        raise ValueError("Choose an installation directory outside the source skill.")
    if destination.exists():
        if not update:
            raise FileExistsError("Skill already exists. Use --update to update it intentionally.")
        manifest = destination / "SKILL.md"
        if not manifest.is_file() or "name: muzhun-subtitles" not in manifest.read_text("utf-8-sig"):
            raise ValueError("Destination is not a Muzhun skill; refusing to overwrite it.")
    python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.is_file():
        raise RuntimeError("Run the project launcher with --install-only before installing the skill.")
    check = subprocess.run([str(python), "-c", "import muzhun; print(muzhun.__version__)"],
                           cwd=ROOT, capture_output=True, text=True, timeout=15)
    if check.returncode:
        raise RuntimeError("The local Muzhun environment cannot load. Run the launcher again.")
    for source in SOURCE.rglob("*"):
        if not source.is_file() or "__pycache__" in source.parts or source.suffix == ".pyc" or source.name == "runtime.json":
            continue
        target = destination / source.relative_to(SOURCE)
        # Updating a skill must not follow a file-level symlink out of its directory.
        if destination not in target.resolve().parents:
            raise ValueError("A destination file resolves outside the skill directory.")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    record = destination / "references" / "runtime.json"
    if destination not in record.resolve().parents:
        raise ValueError("The runtime record resolves outside the skill directory.")
    record.write_text(json.dumps({"root": str(ROOT), "python": str(python),
                                 "version": check.stdout.strip()}, ensure_ascii=False, indent=2), "utf-8")
    return destination


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=list(AGENT_ROOTS), default="codex",
                        help="安装到对应 Agent 的用户技能目录；DeepSeek Harness 用 deepseek")
    parser.add_argument("--destination", type=Path, help="自定义目录，优先于 --agent")
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args(argv)
    try:
        target = install(args.destination or default_destination(args.agent), args.update)
        invocation = {"codex": "$muzhun-subtitles", "claude": "/muzhun-subtitles",
                      "cursor": "/muzhun-subtitles", "deepseek": "/muzhun-subtitles"}.get(args.agent)
        hint = f"Use {invocation}" if invocation else "Ask the agent to use the muzhun-subtitles skill"
        print(f"Installed: {target}\nAgent: {args.agent}\n{hint}, or ask it to read this SKILL.md and run scripts/run.py.")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
