# mark v0.1.5

mark v0.1.5 修复划词 mark 按钮偶尔让整个客户端进入“ChatGPT 遇到了问题”错误页的问题，并补齐升级清理后的辅助进程回收。

## 错误页修复

- 新客户端的划词按钮现在使用该客户端实际导出的 React、JSX 和 Button 模块别名。
- 修复页面或选区浮栏重新挂载时出现的 `useState is not a function` 错误。
- 增加新版模块别名下的重复挂载、保存和取消 mark 回归测试。

## 进程回收

- 删除旧构建时会结束已经没有主窗口的 crashpad 与键盘监听辅助进程。
- 正常切换客户端后会回收刚退出副本的辅助进程。
- 只处理 mark 管理目录和明确对应已退出应用的辅助进程；运行中的客户端保持不变。

## 安装与升级

阅读 [安装说明](https://github.com/yinjialu/mark/blob/v0.1.5/docs/INSTALL.md)，将其中的指令复制给 Codex，或使用终端安装脚本。也可下载 ZIP，解压后双击 `Install.command`。

v0.1.4 用户可在 mark 页面检查更新并安装 v0.1.5。无需迁移收藏数据。

## 支持范围与验证边界

支持范围与 v0.1.4 相同：**macOS Apple Silicon、ChatGPT 26.908.40834 / build 8881 或 26.901.51231 / build 8109**，并要求清单精确匹配原始包哈希。未知版本停止安装，保留上一可用副本。

本版根据客户端日志中的 React error boundary 堆栈定位并修复。收藏数据库 `~/.local/share/codex-marks/marks.sqlite3` 及其 `assets/` 不会被迁移或清理。
