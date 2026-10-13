"""One entry point for installing the engine and the chosen Agent Skill."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from launch import install, ROOT
from install_skill import AGENT_ROOTS, default_destination


def main(argv=None):
    parser = argparse.ArgumentParser(description="安装幕准运行环境和 Agent Skill")
    parser.add_argument("--agent", choices=list(AGENT_ROOTS))
    parser.add_argument("--choose-agent", action="store_true")
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--web-only", action="store_true")
    parser.add_argument("--runtime-record", type=Path, help="自定义引擎定位记录（隔离安装验证时使用）")
    args = parser.parse_args(argv)
    try:
        if args.choose_agent:
            choices = list(AGENT_ROOTS)
            print("选择使用的工具：")
            for index, name in enumerate(choices, 1):
                print(f"  {index}. {name}")
            answer = input("输入编号（回车默认 codex）：").strip() or "1"
            if not answer.isdecimal() or not 1 <= int(answer) <= len(choices):
                raise ValueError("请选择列表内的编号")
            args.agent = choices[int(answer) - 1]
        python = install(ROOT)
        from fonts import ensure_font
        ensure_font(python, ROOT)
        if not args.web_only:
            agent = args.agent or "codex"
            destination = (args.destination or default_destination(agent)).expanduser().resolve()
            command = [str(python), str(ROOT / "scripts/install_skill.py"), "--agent", agent,
                       "--destination", str(destination)]
            if destination.exists():
                command.append("--update")
            subprocess.run(command, cwd=ROOT, check=True)
        # A generic Skills CLI installation can discover this same engine later.
        record = (args.runtime_record or Path.home() / ".muzhun" / "runtime.json").expanduser().resolve()
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps({"root": str(ROOT), "python": str(python)}, ensure_ascii=False), "utf-8")
        print("\n安装完成。双击 Start-Muzhun.cmd 打开网页，或在 Agent 中使用 muzhun-subtitles。")
        print("首次语音识别才会下载所选模型；本次安装没有下载语音模型。")
        return 0
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"安装未完成：{error}\n请修复后重新运行，本地素材和任务不会被删除。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
