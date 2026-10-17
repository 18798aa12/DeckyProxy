# DeckyProxy

在 Steam Deck 的游戏模式里，通过 Decky Loader 管理 Clash 兼容的代理。前端使用 React / TypeScript 和 Decky 的手柄界面，后端使用 Python，代理内核固定为 **Mihomo v1.19.32**。

这是独立项目。安装包面向 **SteamOS / Linux x86_64**；macOS 只用于开发、测试和打包。**尚未完成 Steam Deck 真机验收**，请先阅读[真机检查表](docs/STEAM_DECK_TESTING.md)。

## 第一版功能与边界

- 游戏模式 QAM 面板：启停、TUN 开关、规则 / 全局 / 直连模式、策略组选择和节点延迟检查。
- 导入公网 HTTPS 的 Clash YAML 订阅，或直接粘贴 YAML；保存、切换、更新和删除配置。
- 支持后端安全下载并展开 HTTPS `proxy-providers`。不支持 Base64 订阅、单节点分享链接、本地文件 provider、需要额外请求头的 provider。
- **只提取节点**，重新生成“节点选择 / 自动选择”两个组。订阅里的规则、DNS、TUN、监听端口和原有策略组不会直接使用。
- **规则模式是局域网直连、其余流量代理，并非中国大陆直连分流。** Steam 下载也可能消耗代理流量。游戏的 UDP 能否使用，取决于节点协议和服务商。
- 默认不开启代理，自动启动默认关闭；导入订阅不会接管网络。内核与设置分开存储，停止代理不删除订阅。
- 不修改 `/etc/resolv.conf`、NetworkManager 配置或系统只读分区；不向局域网开放管理端口。

暂未包含完整 Clash 仪表盘、自定义分流规则编辑器、订阅格式转换、二维码导入、自动更新内核或流量额度展示。

## 在 Steam Deck 安装

公开测试包可通过 Decky **设置 → 开发者 → 从 URL 安装插件**，粘贴以下链接安装：

```text
https://github.com/18798aa12/DeckyProxy/releases/download/v0.1.0/DeckyProxy-0.1.0.zip
```

也可以在 [GitHub Releases](https://github.com/18798aa12/DeckyProxy/releases/tag/v0.1.0) 下载 ZIP 后按下面步骤安装。当前版本**未上架官方商店**，原因与条件见[发布说明](docs/PUBLISHING.md)。

1. 先安装并确认 [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) 正常工作。
2. **停止其他 Clash / VPN / TUN 代理**，包括 ToMoon、DeckyClash 或桌面模式里运行的代理客户端，避免争用路由和 DNS。
3. 将 `release/DeckyProxy-0.1.0.zip` 传到 Deck。可先在电脑核对同目录 `SHA256SUMS`：Linux 使用 `sha256sum -c SHA256SUMS`，macOS 使用 `shasum -a 256 -c SHA256SUMS`。
4. 打开 Decky 设置，启用开发者模式，在“开发者”里的“从 ZIP 安装插件”选择安装包。Decky 版本不同，入口文字可能略有差异；本项目尚未上架插件商店。
5. 在 QAM 打开 **DeckyProxy**，输入名称和公网 HTTPS 订阅，点击“导入配置”，选择要使用的配置。
6. 检查模式和 TUN 设置后，手动打开“启用代理”。通常游戏与 Steam 系统流量需要 TUN；关闭 TUN 时只启动本地 HTTP / SOCKS 混合代理端口 `127.0.0.1:19790`，应用需自行使用该代理。

安装 ZIP 自带已校验的 Linux 内核和纯 Python YAML 解析器，无需在 Deck 上安装 Python 包。内核缺失时，面板也提供从官方固定版本安装的按钮，设备需能直连 GitHub。

面板“运行中”和控制器健康检查表示进程已启动且本地 API 可响应；它们不能证明 TUN 路由、DNS、UDP 或公网连通性正常。首次使用请按真机检查表核验。

订阅链接通常含访问令牌。保存后界面只显示来源主机，不回显完整链接；本地保存的订阅和节点仍属于敏感数据，请勿公开分享。

## 停止、恢复与备份

先关闭“启用代理”，等待显示“代理已停止”，再卸载或重载插件。正常卸载会停止本插件启动的内核。后端退出保护会请求内核退出；它不是已经通过真机测试的断网恢复保证。

若网络异常，先停止本插件与其他代理并检查是否恢复直连。Decky 不可用时，可重启 Steam Deck，然后保持本插件自动启动关闭；不要运行来源不明的 DNS 恢复脚本。本插件不会写入系统 DNS 文件，因此不应据此改写这些文件。更多检查见[真机检查与恢复](docs/STEAM_DECK_TESTING.md)。

私密数据均保存在 `DECKY_PLUGIN_SETTINGS_DIR`，通常是 `~/homebrew/settings/DeckyProxy/`：根目录的 `settings.json` 与 `profiles/*.json` 保存设置和订阅，`backend/` 保存内核运行配置、候选配置、缓存与后装内核。**`DECKY_PLUGIN_RUNTIME_DIR` 可通过 Decky 静态 HTTP 访问，不能存放订阅、节点密码、控制器 secret 或含这些内容的运行配置。**

备份或恢复前先停止代理、关闭自动启动并退出插件面板。在桌面模式复制本插件的 settings 目录，并保留文件权限；恢复后重新加载 Decky，再检查设置并手动启动。备份包含订阅凭据，不能公开。不要把日志或整个 ZIP 当作个人配置备份。

## 本地开发与打包

需要 Node.js 22、pnpm 9.15.9 和 Python 3.11+。以下命令在项目目录执行：

```bash
pnpm install --frozen-lockfile
pnpm typecheck
pnpm test
pnpm build

python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m ruff check main.py py_modules scripts tests
.venv/bin/python -m pytest --cov=decky_proxy --cov-report=term-missing
.venv/bin/python scripts/package.py
.venv/bin/python scripts/verify_release.py
.venv/bin/python scripts/sanitize_release.py
```

`package.py` 会按[版本锁定文件](assets/core-lock.json)下载固定内核、对应上游源码和 PyYAML 源码，验证 SHA256，再生成：

```text
release/
├── DeckyProxy-0.1.0.zip
├── DeckyProxy-0.1.0-source.tar.gz
└── SHA256SUMS
```

源码附件包含插件源码、构建脚本和锁定的 Mihomo / PyYAML 上游源码压缩包。**向别人分发安装包时一并提供该源码附件与许可证**；不要只提供上游源码链接。安装 ZIP 不包含用户订阅、运行配置、日志、开发环境或 macOS 扩展模块。

仅在 Linux x86_64 可额外执行：

```bash
.venv/bin/python scripts/linux_smoke.py
```

此检查只执行内核版本查询与配置校验，不启动 TUN、不改变主机路由。真实网络行为仍需在 Steam Deck 验收。CI 同样运行前后端检查、打包和 Linux 配置校验。

## 代码与调研

```text
src/                       Decky QAM 界面与 typed RPC
main.py                    Decky 插件入口、RPC 与生命周期
py_modules/decky_proxy/    配置安全、订阅、存储、内核与控制器
assets/core-lock.json      固定下载地址与压缩/展开 SHA256
scripts/                   内核下载、发布打包、Linux 配置检查
tests/                     后端测试
docs/                      调研、设计边界、真机检查表
```

实现参考了 [DeckyClash](https://github.com/chenx-dust/DeckyClash)、[ToMoon](https://github.com/YukiCoco/ToMoon) 和 [Decky 官方模板](https://github.com/SteamDeckHomebrew/decky-plugin-template)，详见[GitHub 调研与设计](docs/RESEARCH.md)。项目采用 GPL-3.0-only；内核与其他第三方组件保留各自许可，见 [LICENSE](LICENSE) 与[第三方说明](THIRD_PARTY_NOTICES.md)。

已执行的检查、平台限制与尚未完成的真机项目，见[验证记录](docs/VALIDATION.md)。
