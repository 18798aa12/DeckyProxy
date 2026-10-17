# GitHub 调研与第一版设计

调研日期：2026-10-18。以下来源均为项目维护者的 GitHub 仓库或官方文档。

| 项目 | 已有做法与可借鉴之处 | 本项目的取舍 |
| --- | --- | --- |
| [chenx-dust/DeckyClash](https://github.com/chenx-dust/DeckyClash) | 面向 SteamOS 的 Python / React 代理插件，集成 Mihomo、订阅导入、随机控制器密码和本地访问默认设置；BSD-3-Clause | 借鉴前后端职责、独立运行配置和安全默认值。首版缩减仪表盘、远程导入、备份与在线升级等范围 |
| [YukiCoco/ToMoon](https://github.com/YukiCoco/ToMoon) | 从游戏模式管理订阅和 TUN，处理 TCP / UDP；BSD-3-Clause | 借鉴使用流程。README 记录了 Decky 异常后系统 DNS 未恢复导致断网的问题，因此本项目不改写系统 DNS 文件 |
| [SteamDeckHomebrew/decky-plugin-template](https://github.com/SteamDeckHomebrew/decky-plugin-template) | `@decky/ui` 组件、`@decky/api` callable、Python 生命周期、标准存储路径与 ZIP 结构；BSD-3-Clause | 使用当前 Decky 接口；不为前后端通讯另开 Web 服务，不依赖旧式 `serverAPI` |
| [MetaCubeX/mihomo](https://github.com/MetaCubeX/mihomo) | Clash 兼容代理协议、DNS、TUN、策略组、REST 控制器；GPL-3.0 | 固定稳定版本 v1.19.32，不在运行时跟踪 latest/Alpha；产品名不包含官方要求避免使用的 mihomo 名称 |

这些项目表明“Decky 界面 + 原生代理内核”是可行路线。本项目重新实现精简控制层，订阅不直接取得 root 内核配置权限；它不是 DeckyClash 或 ToMoon 的改名分发。

## 运行结构

```text
Steam 游戏模式 / QAM
       ↓ @decky/api typed callable
Decky Python root 插件
       ├─ HTTPS 订阅下载、YAML 校验、节点提取
       ├─ 本地权限受限的设置与运行配置
       ├─ 内核生命周期与父进程退出保护
       ↓ 127.0.0.1 + 随机 Bearer secret
Mihomo REST 控制器 → 策略组 / 节点延迟 / 模式
       ↓
Mihomo TUN → 系统 TCP / UDP 流量
```

TUN 创建和路由管理需要权限，因此 `plugin.json` 声明 Decky 的 `root` flag；不让用户保存 sudo 密码。插件只向本机回环地址开放混合代理和控制器。Python 的订阅下载与 RPC 是需要检查输入的系统边界。

[Decky 官方类型说明](https://github.com/SteamDeckHomebrew/decky-plugin-template/blob/main/decky.pyi)提供 settings、runtime、logs 路径。本项目的 **`DECKY_PLUGIN_SETTINGS_DIR/settings.json`** 和 **`profiles/*.json`** 保存设置、订阅与节点；**`DECKY_PLUGIN_SETTINGS_DIR/backend/`** 保存内核运行配置、候选配置、缓存与后装内核。它们都处于私密 settings 目录。`DECKY_PLUGIN_RUNTIME_DIR` 会被 Decky 静态 HTTP 暴露，不能存放订阅 URL、节点密码、secret 或生成配置。安装目录只放代码与固定资源；更新 ZIP 不应覆盖这些个人数据。

## 配置安全与兼容性

第一版仅使用订阅节点，HTTPS provider 由后端受限下载后展开为节点。它重新创建“节点选择 / 自动选择”两个策略组，不执行订阅的原始规则、DNS、TUN、监听器、外部面板和 provider 文件路径。无法安全支持的本地证书、接口绑定或链式拨号配置会被拒绝；配置不兼容时应明确报错。

规则模式采用“局域网直连，其余走节点选择”。这避免首版依赖 GEO 数据下载，但不提供国内外自动分流，用户要留意下载流量。订阅服务商原有复杂分组、规则集、进程规则和 DNS 策略也不会保留。

[官方 TUN 文档](https://wiki.metacubex.one/config/inbound/tun/)提供 `auto-route`、`auto-detect-interface` 和 `dns-hijack`。本项目让内核管理自己的 TUN 和路由，不持久修改系统 DNS 配置。首版使用 mixed 栈、固定独立 TUN 名和路由索引，默认不启用 `auto-redirect`；与其他 VPN 的冲突必须通过真机验证。

[官方 API 文档](https://wiki.metacubex.one/api/)提供配置、策略组、代理与延迟操作。插件通过 Python 代理这些 API，不在前端保存控制器密钥，也不提供任意 URL / 任意 API 转发能力。

## 生命周期与待验证风险

正常卸载先停止内核；停止采用有界等待，超时回收进程。Linux runner 使用父进程退出信号，减少后端异常终止后内核残留；只管理自己启动的进程，不按名称清除系统其他代理。

最关键的剩余风险是 SteamOS 网络实现、TUN 清理、IPv6 行为和待机唤醒后的接口切换。这些无法由 macOS 单元测试证明。当前不声称支持隐私防泄漏或网络 kill switch；启用代理也不代表所有游戏一定能降低延迟。

本地 HTTP 控制器可响应、`/configs` 返回配置或内核 `-t` 校验成功，只能说明进程/API/配置可用，不能证明 TUN 网卡、系统路由、DNS 接管和 UDP 实际正常。应在产品状态和测试记录中区分这些结果。

构建锁定压缩包和展开内核 SHA256，并校验对应源码。实际安装包同时提供源码附件。ZIP 安装只是本地分发方式；进入 Decky 插件商店仍需按照官方流程提交与审核。
