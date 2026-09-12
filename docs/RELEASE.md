# mark v0.1.4

mark v0.1.4 清理无引用的客户端副本和安装包，让升级后的回退能力保持明确，也避免开发或长期升级后在 Spotlight 中出现大量重复入口。

## 构建回收

- 成功准备或切换后，只保留当前副本、待切换副本和一个回退副本。
- 同步删除这些状态不再引用的安装包；未知目录和用户内容不会被清理。
- 成功升级后只保留最近一个启动器备份。
- 清理失败不会让一次健康的构建或启动回滚，后续成功升级会再次尝试。

## Spotlight

- mark 状态目录写入 `.metadata_never_index`，让内部客户端副本不再参与新的 Spotlight 索引。
- 唯一的公开启动器显示为 **ChatGPT mark**，支持 `ChatGPT` 和 `mark` 搜索词。
- 现有索引缓存会由 macOS 逐步移除。

## 安装与升级

阅读 [安装说明](https://github.com/yinjialu/mark/blob/v0.1.4/docs/INSTALL.md)，将其中的指令复制给 Codex，或使用终端安装脚本。也可下载 ZIP，解压后双击 `Install.command`。

v0.1.3 用户可在 mark 页面检查更新并安装 v0.1.4。无需迁移收藏数据。

## 支持范围与验证边界

支持范围与 v0.1.3 相同：**macOS Apple Silicon、ChatGPT 26.908.40834 / build 8881 或 26.901.51231 / build 8109**，并要求清单精确匹配原始包哈希。未知版本停止安装，保留上一可用副本。

清理只处理 mark 状态目录内带有内部清单的托管构建和安装包。收藏数据库 `~/.local/share/codex-marks/marks.sqlite3` 及其 `assets/` 不在清理范围内。
