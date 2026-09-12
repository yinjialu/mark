# 安装 mark

mark 有两部分：标准 Codex 插件负责收藏和检索；本机界面适配器负责划词浮栏、下划线、图片/图表/表格按钮、右侧导航和内置收藏库。**想使用截图中的界面，需要安装完整包。**

## 复制给 Codex 自动安装

把下面整段发给 Codex 即可。安装完成会重启客户端，请先结束其他正在运行的任务。

```text
请帮我安装 https://github.com/yinjialu/mark 的最新兼容版本。
先阅读 README.md、docs/INSTALL.md 和 install.sh，再下载并运行安装脚本；不要固定旧标签。
我同意下载并校验该仓库的发布包，在本机生成并本地签名 ChatGPT mark 独立副本，仅为副本启用 disable-library-validation，安装 mark 启动器并正常重启切换；保留正式应用、收藏和旧副本。
使用 --yes --no-wait，跟踪返回的结果文件；只有 complete 才报告安装完成，失败请说明原因，不绕过兼容性检查。
```

安装脚本会自己选择新目录、检查工具和客户端、寻找最新兼容发布。用户无需准备 GitHub 凭据或 API key。标准插件是可选项，截图中的界面不依赖额外安装插件。

## 自己安装：终端复制一次

先查看 [install.sh 源码](../install.sh)，再把下面三行一起复制到终端：

```sh
MARK_INSTALL_SCRIPT="$(mktemp -t mark-install)"
curl --fail --show-error --location --proto '=https' --tlsv1.2 https://raw.githubusercontent.com/yinjialu/mark/main/install.sh --output "$MARK_INSTALL_SCRIPT" &&
  bash "$MARK_INSTALL_SCRIPT"
```

脚本会显示可安装版本，输入 `install` 确认后开始下载、校验和安装，终端显示进度与最终结果。成功后打开 **ChatGPT mark**，左侧 **mark** 就是收藏库。

下载脚本和获取 main 分支安装器都需要访问 GitHub；会执行本仓库代码。安装器保存到 `~/Library/Application Support/mark/bootstrap/` 的独立目录，不覆盖已有 checkout。`install.sh` 使用 GitHub HTTPS 获取 main，随后校验包内文件清单；真正的客户端适配包仍从 Releases 按精确兼容性选择并校验。SHA256 是完整性检查，不是开发者数字签名。

常用选项（接在 `bash "$MARK_INSTALL_SCRIPT"` 后面）：

| 选项 | 用途 |
| --- | --- |
| `--check` | 只检查环境和兼容发布，不安装或重启 |
| `--yes` | 明确接受安装提示中的下载、本地签名、启动器安装与重启，省去输入确认 |
| `--no-wait` | 安排后台安装后返回结果/日志路径，适合 Codex 执行；不表示安装成功 |
| `--app '/Applications/Codex.app'` | 指定非默认正式客户端位置 |

断网、缺少工具或没有兼容包时，脚本会停止并给出下一步提示。已是最新兼容版本时直接结束。

## 环境要求

| 项目 | 当前支持 |
| --- | --- |
| 系统 | macOS，Apple Silicon / arm64 |
| ChatGPT | 26.908.40834（build 8881）或 26.901.51231（build 8109），原始 OpenAI 签名 |
| 工具 | Command Line Tools：git、clang、codesign、`/usr/bin/python3` |
| Codex CLI | 可选，仅安装标准插件时需要 |

安装器还会核对原始 ASAR header SHA256，详细值见根目录 `compatibility.json`。相同版本但不同包也可能不支持。Intel Mac、Windows、Linux 和其他客户端版本目前不能使用界面集成。不要为了安装 mark 随意下载来源不明的旧客户端。

如果尚未安装 Command Line Tools，运行 `xcode-select --install`，完成系统安装提示后再继续。安装器不会替你关闭 Gatekeeper 或移除隔离标记；这是没有 Developer ID 签名、公证的社区发布包，系统阻止时应先确认下载来源。

## 进阶：固定版本或已有 checkout

从 [发布列表](https://github.com/yinjialu/mark/releases) 选择兼容版本，下载 ZIP 和 SHA256，校验后解压，双击 `Install.command`，输入 `install`。此方式安装你选定的版本，适合固定版本复现。

也可以让安装器选择最新兼容版本（目标目录须不存在）：

```sh
git clone --branch main --depth 1 https://github.com/yinjialu/mark.git "$HOME/mark"
cd "$HOME/mark"
python3 -B mark.py check-update --force
python3 -B mark.py install-latest --yes --accept-local-resign --detached
```

先检查查询结果：`available` 表示存在可安装的兼容版本；`up_to_date` 表示已安装最新兼容版本；`no_compatible_release` 或 `offline` 时停止。新安装会查询 GitHub 发布信息，不执行下载包中的代码，直到你明确使用 `--yes`。

非默认正式版路径，在命令前加 `--app`，例如 `python3 -B mark.py --app '/Applications/Codex.app' check-update --force`。其他命令也应使用同一路径。

后台更新先等待约 8 秒，再下载、校验、构建并切换。`result_file` 中的 `complete` 表示更新流程已完成；切换期间会检查新进程稳定运行 20 秒，**不替代实际按钮与保存功能验收**。`error` 时查看相邻 log，收藏和旧副本保留。下载或构建失败不会关闭当前客户端；切换失败时尝试重新打开切换前的客户端，并恢复旧启动器。

## 可选：安装标准插件

界面集成不依赖 Codex CLI。标准插件额外支持在任务里检索和导出收藏。

先执行 `codex plugin list`，若已有 `codex-marks`，保留并检查来源，避免重复安装。首次安装：

```sh
codex plugin marketplace add /absolute/path/to/mark
codex plugin add codex-marks@mark
```

将 `/absolute/path/to/mark` 换成 checkout 的绝对路径，并保留该目录；也可使用完整安装返回的 `package` 路径，它位于持久应用支持目录。不要手工覆盖既有 marketplace 配置。使用新任务测试新安装的技能。

## 日常打开、升级与回退

- 首次通过 `~/Applications/mark.app` 启动，将运行中的 **ChatGPT mark** 固定到 Dock；日常从 Dock 打开。完整步骤见[使用指南](USAGE.md#日常只用一个入口)。
- 在左侧 **mark** 收藏页点击 **检查更新**。打开此页时也会自动检查，成功结果缓存 24 小时，网络失败缓存 15 分钟；手动检查跳过缓存。
- 发现兼容更新后，点击 **安装并重启** 确认，或选择 **暂不更新**。只有确认后才下载 ZIP，核对发布包 SHA256、文件清单和兼容性，再构建和切换。
- 成功升级或回退后，已有的 Dock mark 入口自动更新；旧副本保留供回退。
- 正式客户端升级后，先保持日常 ChatGPT mark 副本不变，再运行 `~/Applications/mark.app` 或重新执行 GitHub 安装指令。安装器会读取新的正式版，只在发布包存在精确匹配适配器时生成并切换新副本；没有适配器时继续使用已有副本，等待新的发布包。
- 回退：在安装包目录执行 `python3 -B mark.py rollback --switch --detached`。首次安装没有旧副本时会说明原因。
- 改用正式版：正常退出 ChatGPT mark，再打开原始客户端。

终端也可以更新：

```sh
python3 -B mark.py check-update --force
python3 -B mark.py update --yes --detached
python3 -B mark.py update-status
```

自动选择仅使用本仓库已发布、上传完整且带有更新协议清单的版本，包含公开预览版，排除草稿和不兼容版本；不会自动降级。SHA256 用于检测文件损坏，下载来源由固定仓库的 GitHub HTTPS 地址限定，并非 Developer ID 签名或 Apple 公证。不会静默安装，也不保证未来客户端版本自动兼容。

**preview.11 及更早版本没有更新入口**，需要按上面的新安装流程更新一次。已复制的旧版固定标签指令不会自动改变。更新机制从 preview.12 起提供，更新的是客户端适配器和启动器；可选标准插件仍通过 Codex 插件管理更新。

独立副本与正式版使用原有 Codex 用户环境，**不是隔离账号或沙盒**；不要同时运行多个副本。

## 验收和排错

1. 左侧“插件”下方出现 **mark**；打开后是主内容区页面。
2. 选中回复文字，原生浮栏有 **mark**，点击变为 **✓ mark**；取消选区后出现下划线。
3. mark 页面能找到新收藏，“定位原文”能回到来源；原文变化时可能退到对应消息或轮次；未找到时留在当前任务提示重试，可手动打开收藏库查看快照。
4. 图片、Mermaid、表格旁的书签按钮可保存完整内容；右侧导航悬停有连续波动效果。

入口缺失：先用 `mark.py status` 检查 active 路径，确认打开的是副本。正式应用不会显示这些入口。若启动失败，提交 issue 时只提供 macOS、架构、客户端版本、错误摘要；日志可能包含个人路径，不要直接上传全部日志或对话。

当前尚未完成第二台 Mac 的首次安装和系统信任提示验收。若启动器记录失败，不要反复删除数据或放宽校验来尝试启动。
