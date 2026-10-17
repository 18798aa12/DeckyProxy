# 第三方组件与源码

DeckyProxy 的原创代码以 **GPL-3.0-only** 发布，完整文本见 `LICENSE`。第三方组件保留其自身版权及许可；本项目与 Valve、Decky、MetaCubeX 或参考项目的维护者没有隶属关系。

| 组件 | 本项目使用方式 | 许可与源码 |
| --- | --- | --- |
| [Mihomo v1.19.32](https://github.com/MetaCubeX/mihomo/tree/v1.19.32) | 原样分发官方 Linux amd64-v1 内核，通过子进程和本地 REST API 控制 | GPL-3.0；安装 ZIP 的 `licenses/MIHOMO-LICENSE`、发布源码附件中的 `third_party/mihomo-v1.19.32.tar.gz` |
| [PyYAML 6.0.3](https://pypi.org/project/PyYAML/6.0.3/) | 从固定 sdist 提取纯 Python `yaml` 包，不带平台扩展 | MIT；安装 ZIP 的 `py_modules/yaml/LICENSE`、源码附件中的 `third_party/pyyaml-6.0.3.tar.gz` |
| [@decky/api 1.1.3](https://github.com/SteamDeckHomebrew/loader-api) | Decky 前后端 RPC 辅助代码，部分进入前端 bundle | LGPL-2.1；安装 ZIP 的 `licenses/decky-api-LICENSE`、源码附件的 `third_party/frontend/decky-api/` 包含完整发布包及 `src/` |
| [react-icons 5.5.0](https://github.com/react-icons/react-icons) | 前端图标封装和 Font Awesome 的 `FaNetworkWired` | 封装 MIT，Font Awesome 图标 CC BY 4.0；完整说明位于安装 ZIP 的 `licenses/react-icons-LICENSE`，源码附件含使用的 `fa/`、`lib/` |
| [tslib 2.8.1](https://github.com/microsoft/tslib) | TypeScript 生成代码可能用到的运行时辅助函数 | 0BSD；安装 ZIP 的 `licenses/tslib-LICENSE`，源码附件含对应发布包 |
| [Decky Plugin Template](https://github.com/SteamDeckHomebrew/decky-plugin-template) | 插件结构、API 与打包方式参考 | BSD-3-Clause；原始声明保留于下文 |

React 和 `@decky/ui` 由 Decky/Steam 前端宿主提供，未将其运行时打进本插件。开发工具与测试依赖由 `package.json`、`pnpm-lock.yaml` 和 `requirements-dev.txt` 固定，不装入设备插件目录。

架构与交互另外参考了 [chenx-dust/DeckyClash](https://github.com/chenx-dust/DeckyClash) 和 [YukiCoco/ToMoon](https://github.com/YukiCoco/ToMoon)，两者公开为 BSD-3-Clause；未将它们的项目代码或安装脚本拷贝进本插件。

## 对应源码与重新构建

`assets/core-lock.json` 记录内核压缩包、展开文件、精确版本源码和 PyYAML 的 SHA256 与来源地址。每次 `scripts/package.py` 生成的 `DeckyProxy-<版本>-source.tar.gz` 同时包含本插件源码、构建脚本、上述对应源码和前端已使用库的源码。请将该文件与安装 ZIP 一起分发，而非只提供链接或当前主分支。

解开源码附件后可按 README 的开发步骤构建插件。前端库源码在 `third_party/frontend/`，可以修改后替换对应的 `node_modules` 包再执行 `pnpm build`；上游内核源码压缩包含其构建脚本与 Go 模块文件。安装 ZIP 使用的是官方发布的原始内核；更换或重编译内核后需要同步检查版本锁和许可证，不能沿用旧 SHA256。

## Decky Plugin Template 原始声明

```text
BSD 3-Clause License

Copyright (c) 2024, Hypothetical Plugin Developer
Original Copyright (c) 2022-2024, Steam Deck Homebrew

All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## Font Awesome 图标署名

`FaNetworkWired` 来源于 Font Awesome Free，Copyright Fonticons, Inc.，按 [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/) 使用；图形通过 react-icons 转换为 React 组件，未对原始图形作其他修改。该许可不表示作者认可本项目。
