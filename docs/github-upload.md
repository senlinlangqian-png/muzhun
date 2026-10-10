# 第一次上传 GitHub

本次发布选 **v0.7.0 公开测试版**。GitHub 不会自动判断“测试版”：创建 Release 时勾选 **This is a pre-release / Set as a pre-release** 才会显示这个标记。以后仍在同一仓库更新版本。

你要做的只有：**创建公开仓库 → 上传解压后的源码 → 添加 Topics → 发布测试版附件**。报错和建议统一去仓库的 **Issues**，不用先建网站或买域名。

网页是幕准的操作界面。别人下载、安装并启动后，在自己的浏览器看到同样的界面；每个人保存的是自己的视频和结果。使用 Skill 时，也可以由 Codex 直接处理，无需每次打开网页。

GitHub 存放公开源码，不会自动运行 Python 视频服务。上传后无需购买域名；用户按 quickstart.md 在自己的电脑启动。

## 先取正确的文件

使用本次生成的 `muzhun-0.7.0-source.zip`。Windows 右键 ZIP → 全部解压，打开解压后里面的 `muzhun` 文件夹。这个包只包含公开代码、说明、Skill、测试与合成示例，已经排除本机环境、模型缓存和用户视频。不要直接上传正在运行的项目目录。

## 网页上完成三步

1. 登录 GitHub，打开 [新建仓库](https://github.com/new?name=muzhun&visibility=public)。名称填 `muzhun`，选择 Public（公开）。简介可复制下面一行。勾选 Add README，让空仓库先出现文件列表；上传时会用项目 README 替换它。无需让 GitHub 再生成 .gitignore 或 License，包里已经有。点击 Create repository（创建仓库）。
2. 在仓库页点击 **Add file → Upload files**。源码超过单次 100 个文件限制，分两次上传：第一次在解压的 `muzhun` 文件夹按 Ctrl + A，再按住 Ctrl 点击 `docs` 文件夹取消它的选择，把其余文件和子文件夹拖到上传区域。确认最外层直接有 `README.md`、`src`、`skills`、`scripts`，提交说明填 `Add Muzhun 0.7.0`，点击 Commit changes。第二次再次打开 Upload files，把完整的 `docs` 文件夹拖入，提交说明填 `Add documentation` 后提交。首次上传自己的仓库可直接提交到 main；若页面显示 Propose changes，则按提示提交新分支并创建、合并 Pull Request。上传的是解压后的内容，不是 ZIP；不要把外层整个 muzhun 文件夹套在仓库里面。
3. 两批上传完成后打开 README，确认图片能显示，再看 **Actions** 的检查结果。把仓库链接发给朋友，让他们点 **Code → Download ZIP** 下载并按“第一次使用”安装。出现 CI 失败时保留错误信息再修复。

GitHub 网页每次最多上传 100 个文件、每个文件最多 25 MiB；发布检查会分别核对上述两批的数量和单文件大小。文件夹内的文件也计入数量。操作入口参见 [GitHub 官方上传说明](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository)；仓库可见性参见 [创建仓库说明](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository)。

可以复制的仓库简介：

```text
本地字幕助手：结合画面核对专业术语，避让重要内容，支持 Agent Skill 与 LRC/SRT 编辑。
```

根目录应像这样：

```text
README.md
LICENSE
pyproject.toml
Start-Muzhun.cmd
run.ps1
run.sh
src/
skills/
scripts/
tests/
docs/
.github/
.gitignore
```

仓库文件列表就是代码；下面自动显示的 README 是项目说明。GitHub 不会显示可运行的字幕编辑页面；朋友需下载并在自己电脑启动才能看到同样界面。上传不需要自己先把 Python 环境或模型一起传过去。

## 添加搜索标签 Topics

仓库首页右侧 **About** 旁点齿轮，在 **Topics** 输入以下词，每输入一个按回车，最后 Save changes：

```text
agent-skills
subtitles
speech-recognition
ocr
video-editing
python
codex
claude-code
```

这些是与用途相关的建议词，能帮助分类和搜索，不能保证流量。不要把未实现的功能或“全网首创”写进标签。首次发布更有用的是让人看懂用途、看到演示、按说明安装成功。用自己可公开的专业教程短片展示一个错词修正或遮挡避让例子即可。

**Topics** 是项目搜索标签；Release 的 **Tag `v0.7.0`** 是版本号；Issues 的 **Labels** 是问题分类。这三样用途不同。步骤来源：[GitHub Topics 官方说明](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics)。

## 发布可下载附件（可选）

在仓库右侧打开 Releases，选择创建新发布，标签与标题填 `v0.7.0`，目标分支选择 main。说明可使用 [测试版说明](release-0.7.md) 的更新内容。勾选 **Set as a pre-release**，明确这是公开测试版。把以下四个文件加为附件，等待上传完成，再点击发布：

- `muzhun-0.7.0-source.zip`
- `muzhun-subtitles-skill-0.7.0.zip`
- `muzhun-0.7.0-py3-none-any.whl`
- `SHA256SUMS.txt`

仓库上传代码时使用解压内容；Release 附件保留 ZIP 文件本身。一般用户下载源码 ZIP；只下载 Skill ZIP 仍需另装字幕处理环境。

GitHub 的预发布标记表示让用户试用并反馈，仍可公开下载；它不是平台对功能质量的认证。创建步骤见 [GitHub Release 官方说明](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)。

## 别人在哪里提意见

让用户在仓库顶部点 **Issues → New issue**，选择“安装或使用问题”“功能建议”或“使用提问”。表单会询问系统、版本、具体步骤和应有结果，你在对应 Issue 下回复即可。三类表单已经放进源码包，上传 .github 文件夹后生效；需要在仓库 Settings → General → Features 保持 Issues 开启。

先用 Issues 统一处理就够了，后续问答多了再开 Discussions。你可以在仓库 **Watch → Custom** 中选择 Issues，并检查账号的 [通知设置](https://github.com/settings/notifications)；是否发邮件取决于你的设置。不要假设登录 GitHub 就一定会收到邮件。查看规则见 [GitHub 通知说明](https://docs.github.com/en/subscriptions-and-notifications/concepts/about-notifications)。

公开测试的专业方向先聚焦：**术语错字与误改、字幕遮挡、安装失败、Agent 调用失败**。让用户提供最短可公开样例和对应时间，不用为了每个建议不断增加无关功能。私有视频、日志或音频应先由用户移除不想公开的内容。

## 检查是否上传成功

- 仓库根目录直接显示 `README.md`、`src` 和 `skills`，README 的新版预览图能显示。
- Actions 出现 Windows / macOS / Linux 检查；成功显示绿色，失败先读对应日志，不能把尚未运行的 CI 说成通过。
- 朋友能下载源码并照 quickstart 启动，点击“字幕避让”得到字幕结果；这一步最能检查其他设备是否真的好用。
- 若只是上传了一个 ZIP 到仓库，README 与源码不会直接展示；把 ZIP 解压后按第二步重新上传内容即可。

创建 Public 仓库和发布 Release 都会把内容公开。创建前应确认仓库名称和公开范围；本教程与本地安装包的生成，不代表已经上传或发布。
