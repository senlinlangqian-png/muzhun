"""Install a repository-local environment and launch it. Standard library only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def environment_python(root: Path) -> Path:
    return root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(command: list[str], **kwargs):
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
    return subprocess.run(command, env=env, **kwargs)


def install(root: Path) -> Path:
    configuration = (root / "pyproject.toml").read_bytes()
    version = re.search(r'^version = "([^"]+)"', configuration.decode("utf-8"), re.M).group(1)
    fingerprint = hashlib.sha256(configuration).hexdigest()
    python = environment_python(root)
    if not python.is_file():
        if sys.version_info < (3, 10):
            raise RuntimeError("Install Python 3.12, then run the launcher again.")
        print("Creating local Python environment...", flush=True)
        run([sys.executable, "-m", "venv", str(root / ".venv")], check=True)
    marker = root / ".venv" / "muzhun-install.json"
    try:
        current = json.loads(marker.read_text("utf-8"))
    except (OSError, ValueError):
        current = {}
    # A version check alone misses an editable installation whose dependencies changed.
    modules = ["fastapi", "uvicorn", "multipart", "PIL", "numpy", "av", "imageio_ffmpeg", "rapidocr_onnxruntime", "faster_whisper", "pypinyin", "opencc"]
    probe = run([str(python), "-c", "import muzhun, fastapi, uvicorn, importlib.metadata as m; from importlib.util import find_spec; "
                 f"assert muzhun.__version__ == {version!r} and m.version('muzhun') == {version!r}; "
                 f"assert all(find_spec(name) is not None for name in {modules!r})"],
                capture_output=True)
    if probe.returncode or current.get("fingerprint") != fingerprint or current.get("root") != str(root):
        print("Installing Muzhun dependencies; the first run needs internet access...", flush=True)
        run([str(python), "-m", "pip", "install", "--editable", str(root)], check=True)
        marker.write_text(json.dumps({"version": version, "fingerprint": fingerprint, "root": str(root)}), "utf-8")
    return python


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Install and open the local Muzhun workspace")
    parser.add_argument("--install-only", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=8770)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        python = install(ROOT)
        if args.install_only:
            print("Muzhun environment is installed. No speech model was downloaded.")
            return 0
        from fonts import ensure_font
        ensure_font(python, ROOT)
        command = [str(python), "-m", "muzhun.cli", "serve", "--port", str(args.port)]
        if not args.no_browser:
            command.append("--open-browser")
        return run(command, cwd=ROOT).returncode
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Startup failed: {error}\nSee docs/quickstart.md. Run again after fixing the issue.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
