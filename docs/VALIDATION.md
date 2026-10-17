# v0.2.2 验证记录

日期：**2026-10-18**。开发主机为 macOS / Apple Silicon。**尚未完成 Steam Deck 真机验收**；本记录不把自动化检查当作 TUN、DNS、UDP、休眠或真实 Decky 升级已通过。

## 本地检查

- TypeScript 类型检查、48 项前端测试、Rollup 生产构建通过。
- Python 全量测试、80% 覆盖率门槛、Ruff 与差异空白检查通过；精确数量与覆盖率见对应提交的 CI 输出。
- 回归覆盖原规则/策略组、HTTP/inline provider、YAML/text/MRS、旧版迁移、订阅更新失败保留旧配置、下载期间停止代理、自动安装开关竞态、缓存清理。
- 安全回归覆盖 YAML 合并展开限制、MRS 内部长度限制、私有文件路径、URL/重定向/DNS 检查、错误签名/哈希、ZIP 路径与类型、更新助手健康失败/回滚/断电状态恢复。
- 新增本地 YAML 的逐层无符号链接读取、所有者/大小/编码限制、原生文件选择器取消和异步结果、B 单击/双击/长按、编辑草稿保留回归。
- v0.2.2 根据 Decky 的 `visible || alwaysRender` 渲染条件复现快捷菜单隐藏时文件结果丢失，并验证导入只提交一次、重新打开后显示新配置、选择/导入进度分离、错误在状态轮询后仍保留，以及无效选择的本地提示。
- 完整配置兼容检查覆盖 AnyTLS、内联 WireGuard、IP-ASN、节点筛选和链式拨号、整数 expected-status，以及严格校验后的规则集格式修正。个人配置仅在忽略的私有目录验证，不加入测试样例或发布附件。
- 节点筛选转换为当前名称的精确匹配，避免不同正则引擎的 Unicode 分类差异绕过拨号循环检查；复杂筛选在 CPU/墙钟限时子进程运行，Linux 限制内存，输出大小有上限。冻结的 Decky 后端使用系统 Python，不把 PluginLoader 当成 Python 启动。
- General、TypeScript 和 Python 独立代码审查完成。发现的 YAML/MRS 内存边界、规则文件格式、更新启动失败状态等问题已修复并补回归。
- `pnpm audit --prod` 无已知漏洞；这不覆盖全部开发依赖或证明内核无漏洞。

## 真实内核

使用已核对压缩包 SHA256 的官方 Mihomo v1.19.32 Darwin arm64（`3312a6780652c622890fd4357c6a853bbf865464fd047ac7b7f52dab8de18652`）：

- 通过基础配置与原始策略组、provider、GEO / ASN 规则及 AnyTLS / WireGuard 节点的 `-t` 校验。
- 实际加载 GEOIP CN **10009** 条记录、GeoSite CN **110534** 条记录。
- 实际转换 MRS，短时启动关闭 TUN/代理监听/DNS 的内核，通过鉴权回环 API 确认 classical、inline、MRS 规则集数量非零。
- 测试结束停止自有进程；未修改主机路由或系统 DNS。

发布 ZIP 内只含 Linux amd64-v1 内核。Linux CI 额外运行真实内核同样的配置/规则 API 检查、父进程死亡保护及真实 `renameat2(RENAME_EXCHANGE)` 回归；详见[CI 运行记录](https://github.com/18798aa12/DeckyProxy/actions)。本地不执行 Linux ELF。

更新助手的服务重启与新后端健康确认在单元测试中替换为受控调用；实际目录交换在 Linux 检查。**跨真实 Decky 服务重启、Steam Deck 权限布局和设备断电恢复仍待实机验证**。

## 打包与隐私

安装 ZIP 包含已锁定内核、离线 GEO / DB-IP ASN 数据、纯 Python PyYAML、更新公钥、插件前后端、说明和许可证。对应源码附件包含本项目代码、构建脚本、精确版本内核/PyYAML 源码、GEO 生成脚本和用到的前端库源码；DB-IP 数据源、哈希和 CC BY 4.0 署名随包提供。

`verify_release.py` 核对实际 ZIP/source 的架构、哈希、必需文件、许可与权限；`sanitize_release.py` 检查源码及归档，不输出匹配的秘密值，仅对三个精确 SHA256 的上游源码归档作限定豁免。发行清单在仓库外私钥签名后立即用打包公钥验签；SHA256SUMS 随发布提供。

个人订阅、URL 密钥、运行配置、控制器 secret、日志、私钥和开发环境均不进入发布。个人数据只在 `DECKY_PLUGIN_SETTINGS_DIR`，不放在 Decky 可公开静态读取的 runtime 目录。

## 仍需实机

执行[Steam Deck 检查表](STEAM_DECK_TESTING.md)，尤其验证安装与手柄输入、TUN 接管、DNS/UDP、Wi-Fi 切换、待机唤醒、停止/卸载后的直连恢复以及实际插件自更新。
