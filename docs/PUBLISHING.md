# 公开发布与商店状态

核对日期：2026-10-18。

源码仓库：[18798aa12/DeckyProxy](https://github.com/18798aa12/DeckyProxy)。发布的安装 ZIP、精确版本源码附件及 SHA256SUMS 位于 [GitHub Releases](https://github.com/18798aa12/DeckyProxy/releases)。这是待真机验收的公开测试版本，不是官方商店已审核版本。

## Decky 商店条件

[官方新增插件 PR 模板](https://github.com/SteamDeckHomebrew/decky-plugin-database/blob/main/.github/PULL_REQUEST_TEMPLATE/plugin_addition.md)要求作者确认：

- 大部分提交代码不是由生成式 AI 编写。
- 插件在 SteamOS Stable 与 Beta 通道正常运行。
- 相比已上架的类似插件具有不同或额外功能，并解释差异。
- 如实完成后端类型、许可及第三方测试等项目。

本项目初版的大部分代码由 AI 生成，且尚未完成 Steam Deck 真机验收，因此目前不满足正式新增插件申请的条件。没有勾选不实声明，也没有提交不符合要求的上架 PR。不能承诺审核时间或绕过上述条件。

如果商店政策将来改变，重新核对当时的官方要求，并完成所需实测后再评估提交。当前可从 Decky 的“从 URL 安装插件”入口安装 GitHub 上的测试 ZIP。

## 脱敏范围

- 发布内容使用明确允许列表，不包含个人订阅、节点凭据、控制器 secret、settings、profiles、日志、缓存、环境文件、SSH 文件或开发依赖目录。
- TAR 的用户名、组名、用户 ID、时间等元数据统一处理；源码映射使用相对路径。
- Git 提交使用项目署名和 GitHub noreply 邮箱，不使用本机私人邮箱。公开仓库所属 GitHub 账号仍会显示，这不等同于匿名托管。
- 测试中的 example 域名、合成密码和上游开源作者署名保留。锁定的第三方源码包含上游自己的测试材料，按固定 SHA256 验证，避免修改原始归档。

可复跑的检查：

```bash
python scripts/sanitize_release.py --source-only
python scripts/package.py
python scripts/verify_release.py
python scripts/sanitize_release.py
```

扫描输出仅包含文件位置、规则名称和行号，不输出匹配的秘密值。模式扫描与人工审查都不能保证识别所有可能的秘密；首次发布同时审查了待提交源码、前端构建、安装 ZIP 与源码附件。
