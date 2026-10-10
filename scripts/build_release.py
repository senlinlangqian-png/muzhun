"""Build public archives and a wheel from a fresh source checkout, then verify."""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def main():
    version = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text("utf-8"), re.M).group(1)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "package_source.py")], cwd=ROOT, check=True)
    build_root = ROOT / ".cache" / "release-builds"
    build_root.mkdir(parents=True, exist_ok=True)
    # Keep this small generated checkout for reproducibility. Never reuse a
    # previous build/lib: setuptools may otherwise retain deleted web assets.
    extracted = Path(tempfile.mkdtemp(prefix=f"v{version}-", dir=build_root))
    with zipfile.ZipFile(ROOT / "dist" / f"muzhun-{version}-source.zip") as archive:
        for name in archive.namelist():
            entry = PurePosixPath(name)
            if entry.is_absolute() or ".." in entry.parts or "\\" in name or entry.parts[0] != "muzhun":
                raise ValueError(f"Invalid source archive path: {name}")
        archive.extractall(extracted)
    subprocess.run([sys.executable, "-m", "pip", "wheel", str(extracted / "muzhun"), "--no-deps",
                    "--wheel-dir", str(ROOT / "dist")], cwd=extracted, check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "check_release.py")], cwd=ROOT, check=True)
    print("Public release files are ready in dist. This command does not upload to GitHub.")


if __name__ == "__main__":
    main()
