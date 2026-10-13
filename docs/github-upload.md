# 更新 GitHub 并发布 1.0

你的仓库已经存在：[senlinlangqian-png/muzhun](https://github.com/senlinlangqian-png/muzhun)。不用重新建仓库，也不需要买域名。GitHub 保存代码和下载包，用户下载后在自己的电脑运行。

## 先弄清四个东西

| 名称 | 意义 |
| --- | --- |
| 仓库 Code | 最新源码、说明、Skill、演示与测试；可以持续修改 |
| Commit | 一次保存记录，可以查看这次改了什么 |
| Actions | 自动安装和测试；绿色表示该次检查通过，不表示所有识别都准确 |
| Release | 一个明确版本的下载页面，附源码包、Skill 包等 |

上传源码和发布 Release 是两个动作。源码上传成功不会自动替换旧的发布附件。

## 先更新源码

如果已经准备了 Pull Request（修改提案），打开它查看 Files changed 与 Checks；确认检查通过后合并到 main。这样比一批批拖文件更容易看清修改。

若使用网页手动上传：下载并完整解压新的 `muzhun-1.0.0-source.zip`。进入其中的 `muzhun` 文件夹，确认直接包含 README.md、src、skills 和 scripts；不要上传父目录其他项目。

1. 仓库点 **Add file → Upload files**。先拖入除了 docs 以外的内容，保留目录结构，说明填 `Update Muzhun to 1.0.0` 后 Commit changes。
2. 再上传完整 docs 文件夹。网页每次至多 100 个文件，源码检查会确认上述两批的数量；每个文件不超过 25 MiB。
3. 隐藏的 .github / .gitignore 如果网页拒收，用 GitHub Desktop 或已有修改提案更新；不要把点号去掉或改目录名。
4. 点 **Actions** 查看这一版 Windows / macOS / Linux 检查；失败时打开日志修复，成功再准备 Release。

上传的是**解压后的公开源码**。不要上传 .venv、.cache、outputs、模型或个人音视频。只使用发布源码包，不直接全选正在运行的项目目录。

## 再发新版本

进入 [新建 Release](https://github.com/senlinlangqian-png/muzhun/releases/new)：

1. Tag 新建 **v1.0.0**，Target 选已经包含新版源码的 main。
2. Title 填 **幕准 v1.0.0**，说明使用 [1.0 发布说明](release-1.0.md)。
3. 作为正式版发布时，取消 **Pre-release**。这只是版本标记，歌曲对齐仍保留实验说明。
4. 添加下列四个附件，**ZIP 不解压**，等上传完成，再 Publish release。

```text
muzhun-1.0.0-source.zip
muzhun-subtitles-skill-1.0.0.zip
muzhun-1.0.0-py3-none-any.whl
SHA256SUMS.txt
```

请保留旧的 v0.7.0 和它的附件。新版本使用新的 Tag 与文件名，方便用户回退和报告版本。

## 别人怎么找到和使用

项目主页继续使用 https://github.com/senlinlangqian-png/muzhun ，下载入口是 Releases。README 已区分完整包与 Skill 包，并提供启动、Agent 安装和反馈链接。Topics 用途标签可以保留，不需要为了每次更新重选，也不能保证收藏数。

反馈统一在 **Issues → New issue**，你在同一个问题下回复。安装成功、示例看得懂、真实素材能解决问题，比修改头像或堆标签更影响使用者是否留下。

参考：[GitHub 上传文件](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository)、[发布版本](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)。本地生成发布包不等于已发布到 GitHub。
