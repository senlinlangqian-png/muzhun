# 发给朋友：怎么安装和试用

**下载地址：** https://github.com/senlinlangqian-png/muzhun/releases

第一次下载 `muzhun-版本-source.zip`，完整解压。单独的 `muzhun-subtitles-skill-版本.zip` 只提供 Skill，没有字幕处理引擎。需要 64 位 Python，推荐 3.12。

## 只想做字幕或歌词

Windows 双击 `Start-Muzhun.cmd`，等网页打开；macOS / Linux 在解压目录运行 `sh run.sh`。首次会安装依赖，第一次识别下载模型，不需要 API Key。

视频直接上传，点击“自动生成字幕”。音频打开“音频与歌词”，选择说话或歌曲，上传音频；没有歌词也可以自动识别，再试听改字。歌曲特别是虚拟歌姬可能错字或找不到时间，有正确歌词时建议补充全文。

## 配合本地 Agent

Windows 双击 `Install-Skill.cmd` 选择工具；也可在项目目录运行：

| 工具 | 安装命令 |
| --- | --- |
| Codex | `python scripts/setup.py --agent codex` |
| DeepSeek Harness | `python scripts/setup.py --agent deepseek` |
| Claude Code | `python scripts/setup.py --agent claude` |
| Cursor | `python scripts/setup.py --agent cursor` |
| Gemini / OpenCode / Kimi | `python scripts/setup.py --agent gemini`，或替换为 `opencode` / `kimi` |
| 通用 Agent Skills 目录 | `python scripts/setup.py --agent agents` |

DeepSeek Harness 默认安装到 `~/.dsh/skills/muzhun-subtitles`，支持 `DSH_HOME`。如果你的 Harness 配置读取其他目录，传 `--destination "实际技能目录/muzhun-subtitles"`。其他宿主也可使用自定义目录。运行时需要宿主允许读取文件和执行 Python；普通 DeepSeek 网页聊天不能在本机执行。

重新加载技能后说：

```text
使用 muzhun-subtitles 处理这段音频，生成逐行 LRC 和 SRT。
这是歌曲，保留原文；需要试听或未定位的行请明确列出。
```

在 Codex 可用 `$muzhun-subtitles`。如果宿主没有自动发现技能，让它读取安装目录内的 `SKILL.md`，按说明运行 `scripts/run.py`。安装器与独立运行脚本已验证；每个宿主的完整调用会话需要实际试用确认。

## 帮忙反馈什么

先用自己熟悉的 30–60 秒素材。记录版本、模型和语言，以及：是否顺利安装、哪句识别错、歌词在哪一秒不准、有没有挡画面、能否下载并导入剪辑软件。长片先用一段 10 分钟以上的课程试一下，再按自己设备情况增加长度。

到 [Issues → New issue](https://github.com/senlinlangqian-png/muzhun/issues/new/choose) 选择安装/使用问题或建议。尽量提供具体时间点和愿意公开的短样例；作者会在同一条 Issue 下回复。不要把个人音视频、模型缓存或含私人路径的完整输出包公开提交。
