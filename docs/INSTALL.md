# 安装 mark

mark 有两部分：标准 Codex 插件负责收藏和检索；本机界面适配器负责划词浮栏、下划线、图片/图表/表格按钮、右侧导航和内置收藏库。**想使用截图中的界面，需要安装完整包。**

## 复制给 Codex 自动安装

在自己的 Codex 中粘贴以下内容。它包含本地签名和重启授权；安装前请结束其他正在执行的任务。

```text
请帮我安装 mark：https://github.com/yinjialu/mark ，使用 v0.1.0-preview.10 标签。
请先阅读该版本的 README.md 和 docs/INSTALL.md，检查安装代码和 SHA256SUMS.json。
将该标签克隆到我的用户目录下一个新的 mark 目录，保留已有目录和收藏；不要覆盖已有 checkout。
运行 python3 -B mark.py doctor。只有返回 supported 时才继续；不支持就停止并告诉我检测到的版本，不要绕过版本、签名或完整性检查。
我同意在本机从正式 Codex 生成独立副本、本地重签名，并仅在副本启用 disable-library-validation；同意安装 ~/Applications/mark.app，完成后正常退出当前 Codex 并切换到副本。不要修改正式应用或系统全局安全设置。
执行 python3 -B mark.py install --accept-local-resign。若 Codex CLI 可用且未安装同名插件，再按文档安装可选标准插件；不要删除已有 marketplace 或同名插件。
最后执行 python3 -B mark.py launch --switch --detached。记录返回的 result_file，重启后检查结果；switch_scheduled 只表示已安排，不能当作启动成功。
请告诉我左侧 mark 入口的位置，并提醒我选一段示例文字点 mark 做一次实际保存和定位验收。
```

仓库代码会在本机执行，建议先审阅再运行。完整流程无需提供 GitHub 凭据、API key 或上传任务记录。

## 环境要求

| 项目 | 当前支持 |
| --- | --- |
| 系统 | macOS，Apple Silicon / arm64 |
| Codex | 26.901.51231，build 8109，原始 OpenAI 签名 |
| 工具 | Command Line Tools：git、clang、codesign、`/usr/bin/python3` |
| Codex CLI | 可选，仅安装标准插件时需要 |

安装器还会核对原始 ASAR header SHA256，详细值见根目录 `compatibility.json`。相同版本但不同包也可能不支持。Intel Mac、Windows、Linux 和其他客户端版本目前不能使用界面集成。不要为了安装 mark 随意下载来源不明的旧客户端。

如果尚未安装 Command Line Tools，运行 `xcode-select --install`，完成系统安装提示后再继续。安装器不会替你关闭 Gatekeeper 或移除隔离标记；这是没有 Developer ID 签名、公证的开发者预览包，系统阻止时应先确认下载来源。

## 手动安装

从 [预览版发布页](https://github.com/yinjialu/mark/releases/tag/v0.1.0-preview.10) 下载 ZIP 和 SHA256，校验后解压，双击 `Install.command`，输入 `install`。

也可以在终端执行（目标目录须不存在）：

```sh
git clone --branch v0.1.0-preview.10 --depth 1 https://github.com/yinjialu/mark.git "$HOME/mark"
cd "$HOME/mark"
python3 -B mark.py doctor
python3 -B mark.py install --accept-local-resign
python3 -B mark.py launch --switch --detached
```

检查 doctor 返回 `supported` 后再执行安装。非默认正式版路径可使用 `python3 -B mark.py --app '/Applications/Codex.app' doctor`，其他命令也应带相同参数。

约 8 秒后执行切换，随后观察新进程持续运行 20 秒。后台结果写入命令返回的 `result_file`：`running` 表示通过进程存活检查，**不替代实际按钮与保存功能验收**；`error` 表示失败，应查看相邻 log 和 `~/Library/Application Support/mark/last-launch-error.json`。失败时尝试重新打开切换前运行的客户端。

## 可选：安装标准插件

界面集成不依赖 Codex CLI。标准插件额外支持在任务里检索和导出收藏。

先执行 `codex plugin list`，若已有 `codex-marks`，保留并检查来源，避免重复安装。首次安装：

```sh
codex plugin marketplace add /absolute/path/to/mark
codex plugin add codex-marks@mark
```

将 `/absolute/path/to/mark` 换成 checkout 的绝对路径，并保留该目录；也可使用完整安装返回的 `package` 路径，它位于持久应用支持目录。不要手工覆盖既有 marketplace 配置。使用新任务测试新安装的技能。

## 日常打开、升级与回退

- 打开 `~/Applications/mark.app`，进入适配后的 Codex。收藏库在左侧 **mark**。
- 正式 Codex 升级后，启动器重新检查兼容性。已有适配器时自动生成副本；未知版本停止，等待新的 mark 发布包。
- 更新 mark：把新版解压到新目录，再执行安装命令。旧的已运行副本保留供回退。
- 回退：`python3 -B mark.py rollback --switch --detached`。首次安装没有旧副本时会说明原因。
- 改用正式版：正常退出测试副本后打开原始 Codex 应用。

不自动下载远程补丁，不保证未来版本自动兼容。测试副本与正式版使用原有 Codex 用户环境，**不是隔离账号或沙盒**；不要同时运行多个副本。

## 验收和排错

1. 左侧“插件”下方出现 **mark**；打开后是主内容区页面。
2. 选中回复文字，原生浮栏有 **mark**，点击变为 **✓ mark**；取消选区后出现下划线。
3. mark 页面能找到新收藏，“定位原文”能回到来源；原文变化时可能退到消息或快照。
4. 图片、Mermaid、表格旁的书签按钮可保存完整内容；右侧导航悬停有连续波动效果。

入口缺失：先用 `mark.py status` 检查 active 路径，确认打开的是副本。正式应用不会显示这些入口。若启动失败，提交 issue 时只提供 macOS、架构、客户端版本、错误摘要；日志可能包含个人路径，不要直接上传全部日志或对话。

当前尚未完成第二台 Mac 的首次安装和系统信任提示验收。若启动器记录失败，不要反复删除数据或放宽校验来尝试启动。
