# 官方插件目录收录

截至 2026-09-08，mark 只在本地 personal 来源和 GitHub 分发，尚未提交官方审核。官方上架已暂停，当前以 GitHub 安装与更新为主。插件详情页由 Codex 根据本地清单生成，显示在“插件”里不代表官方收录。

## 提交流程

1. 在 [OpenAI Platform](https://platform.openai.com/plugins) 使用具备 Apps Management Write 权限的组织账号，完成个人或企业开发者身份验证。
2. 创建插件，标准收藏技能可选择 Skills only。准备名称、介绍、Logo、网站、支持入口、隐私政策、条款、技能包、示例提示和测试材料。
3. 测试材料包含 5 个正向用例和 3 个反向用例；验证后选择 Submit for Review。
4. OpenAI 审核通过后，在提交后台发布，才会进入 ChatGPT / Codex 共享插件目录。推送 GitHub 或安装本地 marketplace 不会自动完成这一步。

依据：[官方提交说明](https://developers.openai.com/plugins/deploy/submission)。

## mark 当前需要补齐什么

- 清单已加入 `mark`、`highlight`、`bookmark`、`annotation`、`收藏`、`高亮`、`标记`，短描述也包含 mark / highlight。名称仍为 mark。关键词是发现元数据，不能保证官方搜索排名或即时索引。
- 标准插件负责通过对话保存、搜索、编辑、恢复和导出本地收藏。原生浮栏、高亮线、图片/表格按钮与导航来自另行安装的客户端适配器；不能将完整客户端截图当作 Skills only 插件安装后的效果。
- 提交前需要用未修改的受支持客户端验证完整技能流程，处理技能内对适配器页面的依赖，并准备正式 Logo、公开隐私政策和条款，以及开发者身份与测试材料。目前尚未完成这些上架准备，也不能保证客户端补丁会被官方收录。

清单字段参考：[官方打包说明](https://developers.openai.com/plugins/build/plugins)。
