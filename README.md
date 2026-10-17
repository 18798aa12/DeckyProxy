# DeckyProxy

在 Steam Deck 的游戏模式里，通过 Decky Loader 管理 Clash 兼容的代理。前端使用 React / TypeScript 和 Decky 的手柄界面，后端使用 Python，代理内核固定为 **Mihomo v1.19.32**。

这是独立项目。安装包面向 **SteamOS / Linux x86_64**；macOS 只用于开发、测试和打包。**尚未完成 Steam Deck 真机验收**，请先阅读[真机检查表](docs/STEAM_DECK_TESTING.md)。

## v0.2.1 功能

- 游戏模式 QAM 面板：启停、TUN 开关、规则 / 全局 / 直连模式、策略组选择和节点测速。
- 直接选择下载、文档或桌面目录中的 `.yaml` / `.yml` 文件，也可导入公网 HTTPS 订阅或粘贴 YAML；保留原始策略组、规则及其顺序。本地文件导入不受订阅 HTTPS 限制。
- 编辑时按 B 结束编辑并保留草稿；主页面按一次 B 显示提示，2 秒内再按一次返回 Decky。
- 支持 HTTP / inline 节点与规则 provider；规则集支持 YAML、text 和 domain/ipcidr MRS。后端安全下载到私有缓存，订阅里的任意本地路径不会交给 root 内核。
- 可向当前配置添加远程规则集，选择目标策略组，插入最终 MATCH 前；刷新订阅保留手动添加的规则集。
- URL 订阅定时更新：关闭、6、12、24 小时。关闭面板仍会执行；失败保留旧配置，更新运行中的活动配置会短暂重启内核。
- 插件自动检查新版，另提供“停止代理后自动安装”开关，默认关闭。安装前验证发行签名和 ZIP SHA256；安装会短暂重启 Decky，后端健康检查失败时尝试回滚。
- 支持 AnyTLS、内联密钥的 WireGuard、经过循环检查的链式拨号，以及有界节点筛选表达式。
- 包含固定版本 GEOIP / GEOSITE / DB-IP ASN 数据，使用地理和 ASN 规则无需首次启动再下载。纯域名规则集的错误 classical 声明、纯文本经典规则集的错误 YAML 声明会在严格校验后修正，并在界面提示。
- 默认不开启代理，自动启动默认关闭。监听端口、DNS、TUN 与控制器由插件统一管理；不改系统 DNS 文件。

仅节点订阅继续使用内置“节点选择 / 自动选择”组与局域网直连规则，**不会自动增加中国大陆直连规则**；需要国内直连时导入含对应规则的完整订阅。Steam 下载可能消耗代理流量；游戏 UDP 取决于协议与服务商。

不支持 Base64、单节点分享链接、本地文件 provider、自定义鉴权请求头、脚本、sub-rules、relay 及不受支持的本地文件/接口配置；导入时会明确报错。节点 provider 的 Clash User-Agent 声明由后端固定兼容值代替，下载必须直连。复杂或可能回溯失控的筛选正则会被拒绝。策略组健康检查使用插件固定地址。MRS 需系统 libzstd（SteamOS 已提供），也可使用 YAML/text。不是所有 Mihomo 扩展都兼容，最终由锁定内核校验。

节点筛选在导入时按当前节点计算并转换为精确名称匹配，刷新订阅时重新计算；支持常用 Python/.NET 共有的表达式，部分扩展和 Unicode 分类语义可能与其他 Clash 客户端不同。复杂表达式在限时子进程内处理，Linux 另限制其内存。

### 从 v0.1 升级

v0.1 没有更新模块，需要手动安装一次 v0.2 ZIP。个人配置保持在独立 settings 目录；旧版只保存了节点，升级后请对 URL 订阅点击一次“更新”，才能恢复订阅原本的规则与策略组。粘贴配置请重新导入完整 YAML。

安装新版前先停止代理。自动检查默认开启，检查失败可手动重试；自动安装只有你开启该选项后才会执行，并等待代理停止。缺少 SteamOS 的 systemd、ssh-keygen 或安全目录条件时，界面会提示手动安装。

## 在 Steam Deck 安装

### 大陆网络下载

GitHub 直连或短链接无法访问时，可尝试以下第三方加速线路；加速站只传输公开安装包；网络可用性取决于运营商。使用同版本 SHA256SUMS 核对安装包，或在 v0.2 内使用发行签名验证的更新。

- [加速下载一（ghfast.top）](https://ghfast.top/https://github.com/18798aa12/DeckyProxy/releases/download/v0.2.1/DeckyProxy-0.2.1.zip)
- [加速下载二（gh-proxy.org）](https://gh-proxy.org/https://github.com/18798aa12/DeckyProxy/releases/download/v0.2.1/DeckyProxy-0.2.1.zip)

下载 ZIP 后可在 Decky 的“从 ZIP 安装插件”入口安装；也可将上述加速链接粘贴到“从 URL 安装插件”。安装 ZIP 已包含内核，无需先从 GitHub 下载内核。

校验值见同次发布的 `SHA256SUMS`。精确版本源码附件随 [v0.2.1 发布](https://github.com/18798aa12/DeckyProxy/releases/tag/v0.2.1)提供。

### 原始发布链接

公开测试包可通过 Decky **设置 → 开发者 → 从 URL 安装插件**，粘贴以下链接安装：

```text
https://github.com/18798aa12/DeckyProxy/releases/download/v0.2.1/DeckyProxy-0.2.1.zip
```

也可以在 [GitHub Releases](https://github.com/18798aa12/DeckyProxy/releases/tag/v0.2.1) 下载 ZIP 后按下面步骤安装。当前版本**未上架官方商店**，原因与条件见[发布说明](docs/PUBLISHING.md)。

1. 先安装并确认 [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) 正常工作。
2. **停止其他 Clash / VPN / TUN 代理**，包括 ToMoon、DeckyClash 或桌面模式里运行的代理客户端，避免争用路由和 DNS。
3. 将 `release/DeckyProxy-0.2.1.zip` 传到 Deck。可先在电脑核对同目录 `SHA256SUMS`：Linux 使用 `sha256sum -c SHA256SUMS`，macOS 使用 `shasum -a 256 -c SHA256SUMS`。
4. 打开 Decky 设置，启用开发者模式，在“开发者”里的“从 ZIP 安装插件”选择安装包。Decky 版本不同，入口文字可能略有差异；本项目尚未上架插件商店。
5. 在 QAM 打开 **DeckyProxy**，点击“选择 YAML 文件并导入”，选择先前下载的配置；也可输入名称和公网 HTTPS 订阅，点击“导入配置”。然后选择要使用的配置。
6. 检查模式和 TUN 设置后，手动打开“启用代理”。通常游戏与 Steam 系统流量需要 TUN；关闭 TUN 时只启动本地 HTTP / SOCKS 混合代理端口 `127.0.0.1:19790`，应用需自行使用该代理。

安装 ZIP 自带已校验的 Linux 内核和纯 Python YAML 解析器，无需在 Deck 上安装 Python 包。内核缺失时，面板也提供从官方固定版本安装的按钮，设备需能直连 GitHub。

面板“运行中”和控制器健康检查表示进程已启动且本地 API 可响应；它们不能证明 TUN 路由、DNS、UDP 或公网连通性正常。首次使用请按真机检查表核验。

订阅链接通常含访问令牌。保存后界面只显示来源主机，不回显完整链接；本地保存的订阅和节点仍属于敏感数据，请勿公开分享。

本地导入只允许当前 Deck 用户拥有的普通 UTF-8 YAML 文件，最大 4 MiB，且位于下载、文档或桌面目录（包括对应的 XDG 目录）；拒绝符号链接、隐藏目录与越界路径。导入后保存独立配置，原文件可移走。本地 YAML 的更新通过重新导入完成。

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

`package.py` 会按[版本锁定文件](assets/core-lock.json)下载固定内核、对应上游源码和 PyYAML 源码，及 GEO 数据和生成脚本，验证 SHA256，再生成：

```text
release/
├── DeckyProxy-0.2.1.zip
├── DeckyProxy-0.2.1-source.tar.gz
├── SHA256SUMS
├── update.json       # 发行者单独签名后生成
└── update.json.sig
```

源码附件包含插件源码、构建脚本和锁定的 Mihomo / PyYAML 上游源码压缩包。**向别人分发安装包时一并提供该源码附件与许可证**；不要只提供上游源码链接。安装 ZIP 不包含用户订阅、运行配置、日志、开发环境或 macOS 扩展模块。

仅在 Linux x86_64 可额外执行：

```bash
.venv/bin/python scripts/linux_smoke.py
```

此检查执行内核版本、配置校验及短时回环 API 检查，确认规则集实际加载；关闭 TUN 和代理监听，不改变主机路由。真实网络接管仍需在 Steam Deck 验收。CI 同样运行前后端检查、打包和 Linux 内核检查。

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
