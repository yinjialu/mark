# 适配与发布流程

本包的 `integration/patch_client.py` 和 `integration/src/` 是当前适配器源码，标准插件位于 `plugins/codex-marks/`。`compatibility.json` 声明允许的官方版本、build、架构及原始 ASAR header SHA256。

## 新版适配

1. 获取并检查正式版原始签名与版本，不在正式应用上编辑。
2. 静态检查原生浮栏、内容按钮、导航、组件导出和 IPC 初始化的变化。
3. 更新 `patch_client.py` 的结构断言、资源路径、组件绑定和版本/hash 常量，以及 `compatibility.json`。只改版本号或仅加入新的 hash 不构成适配。
4. 对选区 UTF-16 坐标、重复原文、图片/图表/完整表格、右侧导航、原生收藏库、跨任务跳转和回收站运行回归测试。对历史懒加载、原文变化、权限拒绝、启动失败和上一版回退进行验证。
5. 确认模板只复用本机构建得到的宿主组件；不打包提取后的客户端 JS、样式表、应用或签名材料。
6. 更新发布版本，重新生成 SHA256SUMS；扩大支持范围或退出预览阶段前，在独立机器完成安装和实际客户端点击验收。预览发布必须列出尚未完成的验收。

当前适配器仅实现 manifest 中的一种版本。未来若同时支持多种客户端，应将每个版本的适配器独立成模块，再由精确匹配的清单选择。不得放宽版本/hash 校验以声称支持未知客户端。

## 测试

`tests/test_manager.py` 使用临时状态目录验证未知版本、状态提交、回退选择、包校验和路径边界。不会读写用户收藏库。开发工作区另有实际原生组件独立测试和客户端补丁回归测试；不随分发包附带已提取的宿主代码。

构建产物和状态应写在包目录之外，防止改变包校验值。标准插件保持 `.codex-plugin/plugin.json`。市场条目由 Codex plugin-creator 生成，不手工改写使用者现有市场配置。

## 当前验证边界

发布包完整性、CLI 检查和在开发机上从正式应用重新构建、重签名及启动版本检查可以自动验证。首次登录、系统信任提示、第三方 Mac 的使用环境和正式版未来升级无法用这些检查替代。

## 打包

```sh
python3 -B -m unittest discover -s tests -v
node --test tests/*.test.cjs
python3 -B scripts/checksums.py
python3 -B mark.py doctor
```

更新清单前检查待发布文件，禁止添加客户端应用、提取的完整 JS/CSS、签名材料、数据库、未经用户授权公开的真实截图或对话。Git 元数据不参与包校验，也不复制到安装目录。将干净提交打标签后用 `git archive` 生成 ZIP，单独发布 ZIP 的 SHA256；校验值用于完整性检查，不是发布者数字签名。

## 更新发布协议

从 preview.12 起，`compatibility.json` 声明 `update_protocol: 1`。每次发布须一起上传 ZIP、对应 `.zip.sha256` 和该版本的 `compatibility.json`；先创建草稿并上传全部资产，再发布。缺失任一文件的版本不参与自动选择。发布后不要移动标签或替换已有资产，应发布新版本。

更新器读取 [GitHub Releases API](https://docs.github.com/en/rest/releases/releases)，包含公开预览版，按版本号排序，匹配本机客户端版本、build、架构和 ASAR header 哈希。检查只下载元数据，安装需用户确认。下载 ZIP 后核对发布资产摘要、外部 SHA256、包内文件清单和兼容性；拒绝路径穿越、符号链接、重复路径和超大解压包。

`upgrade` 在同一个安装锁内完成构建、启动器替换和启动检查。失败时恢复旧启动器及 active/prepared/previous 状态；成功后沿用 Dock 更新机制。网络与更新进度保存到用户状态目录，仓库不包含这些文件。
