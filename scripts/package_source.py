"""Bundle public source and the skill without local videos, models, or runtime paths."""
from pathlib import Path
import json
import re
import zipfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = ["README.md", "README.en.md", "LICENSE", "pyproject.toml", ".gitignore", "run.ps1", "install-skill.ps1",
              "Start-Muzhun.cmd", "Install-Skill.cmd", "run.sh", "CONTRIBUTING.md", "requirements-tested-windows.txt", "CHANGELOG.md"]
DEMO_FILES = ["demo.mp4", "demo-input.srt", "demo-truth.json", "demo-provenance.json",
              "dynamic-demo.mp4", "dynamic-input.srt", "dynamic-truth.json", "dynamic-provenance.json",
              "lyrics-demo.wav", "lyrics-demo.txt"]


def main():
    files = [ROOT / name for name in ROOT_FILES] + [ROOT / "examples" / name for name in DEMO_FILES]
    for folder in (".github", "docs", "src", "skills", "scripts", "tests"):
        files.extend(path for path in (ROOT / folder).rglob("*") if path.is_file()
                     and "__pycache__" not in path.parts and path.suffix != ".pyc"
                     and not any(part.endswith(".egg-info") for part in path.parts)
                     and path.name != "runtime.json")
    missing = [str(path.relative_to(ROOT)) for path in files if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing release files: {missing}")
    # Manifest validation alone does not validate the display metadata encoding.
    skill_root = ROOT / "skills" / "muzhun-subtitles"
    metadata = yaml.safe_load((skill_root / "agents" / "openai.yaml").read_text("utf-8"))
    if not metadata["interface"]["display_name"] or not metadata["interface"]["default_prompt"]:
        raise ValueError("Missing skill display metadata")
    version = re.search(r'^version = "(.*?)"', (ROOT / "pyproject.toml").read_text("utf-8"), re.M).group(1)
    destination = ROOT / "dist" / f"muzhun-{version}-source.zip"
    destination.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(files)):
            archive.write(path, "muzhun/" + path.relative_to(ROOT).as_posix())
    print(f"Created {destination} ({len(set(files))} files, {destination.stat().st_size:,} bytes)")
    import shutil
    shutil.copyfile(destination, ROOT / "dist" / "muzhun-source.zip")
    skill_zip = ROOT / "dist" / f"muzhun-subtitles-skill-{version}.zip"
    skill_files = [path for path in files if path.is_relative_to(skill_root)]
    with zipfile.ZipFile(skill_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(skill_files)):
            archive.write(path, "muzhun-subtitles/" + path.relative_to(skill_root).as_posix())
    print(json.dumps({"skill_zip": str(skill_zip), "files": len(skill_files), "engine_included": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
