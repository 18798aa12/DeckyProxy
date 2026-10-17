# 验证记录

日期：**2026-10-18**。以下记录针对本地 0.1.0 源码与发布包，开发主机为 macOS / Apple Silicon。

**尚未进行 Steam Deck 真机验收。** 当前检查证明源码、用户态内核控制与打包流程可运行，不能证明 SteamOS 的 TUN 路由、DNS 接管、UDP、待机唤醒或卸载后网络恢复正常。

## 已完成

| 检查 | 实际结果 |
| --- | --- |
| Python 后端与发布测试 | **84 passed，1 skipped**（含 7 项脱敏检查回归）；后端覆盖率 **88.13%** |
| Linux runner 回归 | 已添加真实父进程死亡回归测试；在 macOS 跳过，需 Linux 运行验证 |
| 前端测试 | **21 tests passed** |
| TypeScript / 前端构建 | `pnpm typecheck`、`pnpm build` 通过；最终 `dist/index.js` 为 30,382 bytes |
| 固定依赖安装 | pnpm **9.15.9** 的 `CI=true pnpm install --frozen-lockfile` 实际通过，无锁文件变更；安装后再次通过 typecheck、21 个前端测试和 build |
| Python 静态检查 | `ruff check main.py py_modules scripts tests` 通过 |
| 生产依赖审计 | `pnpm audit --prod` 返回 **No known vulnerabilities found**；这不覆盖测试依赖或证明代理内核没有漏洞 |
| 代码审查 | Python reviewer 与 general code review 通过；没有剩余 P1/P2 问题 |
| 发布工具错误路径 | 错误 SHA256 被拒绝且无临时缓存残留；已验证缓存复用；HTTP 输入与源码符号链接被拒绝 |
| ZIP / 源码附件审计 | 校验 Linux ELF 架构与固定 SHA256、核心执行权限、纯 Python YAML 包、许可证、源码附件和私密数据排除；每次发布可重跑 `scripts/verify_release.py` |
| 公开发布脱敏 | `scripts/sanitize_release.py` 检查 Git 源码和两份归档，输出位置/类别/行号，不输出秘密值；只对两份 SHA256 已验证的精确上游归档作豁免 |

依赖审计是截至检查时公开漏洞数据库的结果，并不替代代码审查、更新评估或真实设备验证。

## 实际内核检查

下载官方 **Mihomo v1.19.32 darwin-arm64** 压缩包，并核对 SHA256：

```text
3312a6780652c622890fd4357c6a853bbf865464fd047ac7b7f52dab8de18652
```

- 将插件生成的 TUN 关闭和 TUN 开启两种配置分别交给该内核执行 **`-t` 配置校验**，均通过。TUN 开启配置只做解析校验，没有在主机启动 TUN。
- 仅使用 **TUN 关闭**的配置启动 macOS 用户态内核，实际请求 `GET /version`、`GET /configs`、`GET /proxies` 均成功，随后停止进程。
- 未修改主机 DNS 配置或系统路由，未使用该内核接管 macOS 系统网络。

安装 ZIP 内是 **Linux amd64-v1** 内核，不包含 macOS 内核。Linux 资产已验证官方固定压缩 SHA256、展开 SHA256 和 ELF64 x86_64 标识；**本机没有执行 Linux 内核**。无可用 Docker daemon，因此没有本地 Linux 容器结果。CI 定义了 Linux `-v` / `-t` 检查，但未将未运行的 CI 当作已经通过。

本地 HTTP API 可响应或 `-t` 成功不代表 TUN、DNS、UDP 和公网连通性健康；界面的运行状态也不能替代这些实测。

## 私密存储与分发核验

设置位于 `DECKY_PLUGIN_SETTINGS_DIR/settings.json`，订阅与节点位于 `profiles/*.json`，含 secret 的运行/候选配置、缓存和后装内核位于 `backend/`。可被 Decky 静态 HTTP 暴露的 `DECKY_PLUGIN_RUNTIME_DIR` 不应保存这些数据。

发布 ZIP 按允许列表生成，包含 Linux 内核、插件前后端代码、纯 Python PyYAML、说明和许可证，不包含个人 settings、订阅、运行配置、日志、虚拟环境、Node 开发依赖或 macOS `.so`。源码附件包含项目源码、构建脚本和精确版本的上游源码压缩包。产物最终校验值见发布目录的 `SHA256SUMS`。

## 待 Steam Deck 实测

完整步骤见[真机检查表](STEAM_DECK_TESTING.md)。优先验证 Decky 安装和手柄交互、TUN 实际接管、DNS/UDP、节点与模式切换、Wi-Fi/扩展坞切换、待机唤醒、异常退出和停止/卸载后的直连恢复。完成这些检查前，版本应视作**待真机验收的首版**。
