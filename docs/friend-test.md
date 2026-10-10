# 发给朋友试用：幕准 0.7

发送完整 `muzhun-0.7.0-source.zip`。朋友需在自己的电脑解压并安装处理环境；不要把作者的 .venv、模型缓存或 runtime.json 一起复制。单独 Skill ZIP 只含操作说明和启动脚本，不含字幕引擎。

## 先体验网页

Windows 安装 64 位 Python 3.12，解压后双击 Start-Muzhun.cmd，等待安装与网页打开，保留启动窗口。无 Agent 也可以直接使用。安装和首次模型下载需要联网，字幕处理在本机执行。

- 视频：先点击“字幕避让”示例，再用自己的 30–60 秒教程或游戏片段，核对术语和遮挡。
- 歌词：点击顶部“歌词 LRC”，选择音频，粘贴一行一句的完整歌词，重复副歌也按演唱顺序写全。或导入 TXT / LRC / SRT。点击“生成歌词草稿”。
- 点击歌词行并试听，可用“当前时间作起点 / 终点”修正，保存后再标记复核；也可整体提前或延后。没有匹配到的行显示“未定位”，补齐后才能导出完整 LRC/SRT。
- LRC 是逐行滚动歌词；SRT 用于剪辑。这里没有逐字卡拉 OK 高亮。已有 LRC/SRT 保留自己的时间并跳过识别；歌词留空则正文来自自动转录。
- 中文自动转录默认输出简体，原始识别文字仍保留；识别设置可选“保留识别字形”。你提供的歌词不会自动改成简体。已有结果也可点“文字转为简体”，误改用撤销恢复。
- 识别完才拿到正确歌词：展开“补充正确歌词 / 重新对齐”，粘贴或导入完整歌词并应用。0.7 复用已保存的锚点，不重跑识别；旧结果可撤销。0.6 旧任务需要重新上传音频，或直接导入带时间的 LRC/SRT。
- 优先处理“对齐待检查”和“未定位”的行，再点“下一句待复核”。识别锚点与文字匹配比例帮助查错，不是正确率。虚拟歌姬等素材可能有很多行无法定位，这个功能仍在试验中。

项目自带 examples/lyrics-demo.wav 与 lyrics-demo.txt。它们是原创英文文字的系统合成朗读，含停顿和重复句，供检查程序是否能运行；不是演唱效果测试，不计为歌曲准确率。

## DeepSeek Harness

在解压的 muzhun 文件夹内打开终端，完成一次网页启动后运行：

```powershell
.\.venv\Scripts\python.exe scripts/install_skill.py --agent deepseek
```

或在 PowerShell 中运行 `./install-skill.ps1 -Agent deepseek`；再次安装同名技能加 --update / -Update。默认位置是 `~/.dsh/skills/muzhun-subtitles`，设置了 DSH_HOME 则安装到 DSH_HOME/skills。安装程序会为朋友的电脑生成自己的运行环境记录。

在本地 DeepSeek Harness 的 Standard / Code 等有 Skill 与 shell 能力的会话中，输入 `/muzhun-subtitles` 加上任务和文件完整路径。可复制：

```text
/muzhun-subtitles
用幕准处理我提供的音频和歌词，保留歌词原文，生成逐行 LRC 和 SRT。
音频路径：填你的音频完整路径
歌词路径：填你的 TXT 完整路径
输出目录：填一个新的输出目录
先检查运行环境，再实际执行 Skill 的 scripts/run.py。
检查未定位的行和对齐提示；不要按总时长平均分配时间，也不要把草稿标成已人工复核。
```

首次只想验证安装，可让 Agent 运行 Skill 的 `scripts/run.py doctor`，再处理随包的 lyrics-demo.wav 和 lyrics-demo.txt，选择 base、language en。Doctor 不下载模型；实际识别首次下载所选模型。

如果 / 菜单看不到技能，确认 Skill 文件夹直接位于 skills 下，没有多套一层；确认当前模式启用了 skill-filesystem 与 tool-skill。可以新开会话，或明确让 Agent 读取已安装的 SKILL.md 并执行脚本。远程 / 容器会话需要把源码、Python 环境和输入文件安装在同一执行环境，不能直接使用本机路径。

这些目录与调用方式按 [DeepSeek 官方 Skill 文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/README.md) 和 [Skill 工具文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/tool-skill/README.md) 适配。发布前验证了安装脚本与安装后启动器；尚未使用朋友的 Harness 实际模型会话验收。

## 其他 Agent

同一条安装命令替换 --agent 参数：

| 参数 | 本机目录 | 常用调用 |
| --- | --- | --- |
| codex | CODEX_HOME/skills 或 ~/.codex/skills | $muzhun-subtitles |
| claude | ~/.claude/skills | /muzhun-subtitles |
| cursor | ~/.cursor/skills | /muzhun-subtitles |
| gemini | ~/.gemini/skills | 自然语言要求使用 muzhun-subtitles；/skills list 检查发现 |
| opencode | ~/.config/opencode/skills | 自然语言要求使用 muzhun-subtitles |
| kimi | ~/.kimi/skills | 自然语言要求使用 muzhun-subtitles |
| agents | ~/.agents/skills，DSH_AGENTS_HOME 可覆盖 | 由对应 Agent 发现 |

macOS / Linux 使用 `.venv/bin/python scripts/install_skill.py --agent deepseek` 等。自定义目录用 --destination；每个目标都执行同一个 Skill 和 Python CLI。Agent 必须有文件访问和执行 Python 的能力；普通聊天窗口只读到说明，并不能自动运行本地引擎。

目录来源：[Claude Code 官方说明](https://code.claude.com/docs/en/skills)、[Cursor 官方说明](https://cursor.com/docs/skills)、[OpenAI 官方说明](https://learn.chatgpt.com/docs/build-skills)。提供格式适配不等于每款 Agent、每个版本或所有设备均已实测。

新增目录按 [Gemini CLI 官方说明](https://geminicli.com/docs/cli/skills/)、[OpenCode 官方说明](https://opencode.ai/docs/skills/)、[Kimi Code CLI 官方说明](https://github.com/MoonshotAI/kimi-cli/blob/main/docs/en/customization/skills.md) 适配。当前 OpenAI 文档也列出 ~/.agents/skills，新装 Codex 可选择 --agent agents；--agent codex 保留本机已验证的 CODEX_HOME / ~/.codex 路径。选一个目录安装即可，避免同名副本版本不同。

不会使用快捷菜单时，给 Agent 发送：

```text
请读取已安装的 muzhun-subtitles/SKILL.md，按它的说明实际执行 scripts/run.py。
先运行 doctor，再处理我提供的视频、音频或字幕文件。
如果没有文件访问或执行 Python 的能力，明确说明缺少什么，不要假装处理完成。
```

普通聊天网页能否执行取决于它提供的运行环境与文件权限；本包没有部署一个让所有聊天网页直接连接的在线服务。无需 Agent 的用户可直接使用本机网页。

## 朋友反馈什么最有用

公开发布后，在仓库 **Issues → New issue** 选择报错、功能建议或使用提问，作者会在那里回复。

先用一段自己熟悉、歌词来源明确的 30–60 秒音频，包括一段前奏或间奏和重复句。记录：是否成功安装、多少行未定位、哪几句提前或延后、手动修正了哪些时间、输出在自己的播放器或剪辑工具里是否正常。保留 lyrics-result.json 与错误截图，再把反馈发回作者。

当前用 faster-whisper 识别时间锚点、按歌词顺序做文字匹配，保留原文并允许试听修正。伴奏、和声、拖音、说唱与漏写歌词都可能导致时间偏差。匹配覆盖率是文字匹配比例，不能当成时间准确率。视频的术语—画面—避让联动仍是项目的主要工程特色；增加 LRC 扩大用途，不代表这项能力是首次出现。
