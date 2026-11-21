# PassIPV6

[![CI](https://github.com/haitun001/luci-app-passipv6/actions/workflows/release.yml/badge.svg)](https://github.com/haitun001/luci-app-passipv6/actions/workflows/release.yml)
[Releases](https://github.com/haitun001/luci-app-passipv6/releases) · [Apache-2.0](LICENSE)

原生 LuCI IPv6 MAC 白名单插件，入口为 **服务 → PassIPV6**。
勾选允许使用 IPv6 的设备，然后保存并应用。IPv4 继续可用。

**1.1.0：保持原网段和纯 AP 布局，按白名单递送 IPv6 路由通告。**
升级或修改权限后，请将受影响设备断开并重新连接一次，以刷新旧路由和 DNS。
真实 iOS 的使用体验需要单独验收，不能将 Linux 测试等同于 iOS 已修复。

## 功能

- 动态发现 LAN 设备，显示名称、MAC、IPv4、IPv6 和发现状态。
- 每 5 秒刷新，保留未保存的选择和键盘焦点，离线白名单不会丢失。
- “保存”只暂存；“保存并应用”显示进行中状态，并根据实际规则确认结果。
- 原生英文和简体中文界面，支持键盘操作与读屏状态提示。
- 独立的 nftables 规则，以原子事务更新；支持防火墙重载和开机恢复。
- 本机 IPv6 路由通告仅递送给白名单 MAC，避免未授权设备继续收到可用 IPv6 路由和 DNS 通告。
- 安装脚本支持首次安装、覆盖旧版本和同版本重复安装，保留已有白名单。

## 支持条件

| 项目 | 要求 |
| --- | --- |
| 系统 | ImmortalWrt **25.12.1 及更高正式版本** |
| 首版验证架构 | x86/64 |
| 页面与运行时 | LuCI JavaScript 页面、rpcd-mod-ucode、ucode fs/uci/ubus 模块、ip-full、libjson-c |
| 防火墙 | firewall4 / nftables，必须通过入口与桥过滤能力检查 |
| LAN | 可用的 Linux bridge，由 UCI 自动识别设备和成员 |
| 路由通告 | 原生 AF_PACKET 与本机生成的 RA；不支持 RA relay/hybrid 模式 |
| 加速 | 可使用受支持的软件加速；硬件卸载、桥成员直接加入 flowtable 不支持 |

不设置系统版本上限；更高版本必须继续提供所需原生接口并通过安装预检。
未来版本尚未实测时，不把它列为已验证平台。首版一键脚本不支持 OpenWrt、
24.10、Snapshot 或其他架构。

运行依赖缺失时，先通过系统软件包管理器补齐。安装脚本只安装两个发布包，
不升级其他软件、不更换内核、不强装内核模块。

## 一条命令安装、升级或重装

**首次安装白名单为空，LAN IPv6 默认受限。请通过 IPv4 管理连接执行。**
升级和重复安装保留已有白名单、接口设置和恢复配置。

以下命令安装最新正式版。先完整下载安装脚本，再执行；脚本固定下载自己对应
Release 的两个 APK，验证 SHA-256，检查实际兼容性，最后核验运行状态。

<!-- install-command -->
```sh
( set -eu; d="$(mktemp -d /tmp/passipv6-bootstrap.XXXXXX)"; trap 'rm -rf "$d"' EXIT; url=https://github.com/haitun001/luci-app-passipv6/releases/latest/download/install.sh; if command -v curl >/dev/null 2>&1; then curl -fsSL --retry 2 --connect-timeout 10 --max-time 60 -o "$d/install.sh" "$url"; else uclient-fetch -q -T 60 -O "$d/install.sh" "$url"; fi; sh "$d/install.sh" )
```

完成后刷新 LuCI 页面。应用菜单为 **服务 → PassIPV6**。
同版本重新执行也会覆盖程序文件，适合修复缺失或损坏的插件文件；配置仍会保留。

安装时使用 `apk add --force-reinstall --allow-untrusted` 安装经过校验的本地包。
这不改变系统的全局签名信任设置。下载和安装暂存均使用独立目录并自动清理。
也可从指定 Release 手动下载两个 APK，校验后使用包管理器安装。

卸载：

```sh
apk del luci-i18n-passipv6-zh-cn luci-app-passipv6
```

卸载删除插件的规则和具名 include。单独停止 init 服务不会解除已生效的保护；
已有配置和恢复文件可能作为配置文件保留。

## 工作方式与边界

入口过滤在软件 flowtable 之前按源 MAC 拦截，桥出口按目标 MAC 拦截未经授权的
IPv6 单播；已取得地址和已有加速连接也受限制。原始组播 RA 在桥出口被拦截。
原生辅助进程保留 odhcpd 生成的通告内容，按白名单改为二层单播递送，符合
[RFC 6085](https://www.rfc-editor.org/rfc/rfc6085)。副本通过原桥发送，仍受出口过滤约束。
两个表在一次 nft 事务中更新，辅助进程确认当前策略后才报告应用成功。

原有防火墙、DNS、代理和广告过滤逻辑继续生效；授权只解除本插件的限制。
插件保留现有 DHCPv6 和 SLAAC 设置，以及 IPv6 所需的其他组播。
辅助进程异常时保留通告拦截、报告失败并由 procd 恢复；故障期间允许设备的
IPv6 配置可能无法续期，不会通过重新放开组播掩盖故障。

未授权设备可能仍显示旧 SLAAC 或自行生成的 `fe80::` 地址，但不能据此经本路由器进行
IPv6 单播通信或获得 DHCPv6 租约。升级或取消授权后需重连一次，以刷新客户端缓存；
未刷新缓存时仍可能出现 IPv6 超时和 IPv4 回退等待。下游 AP／交换机内部不经过路由器
的通信和其他设备私自发出的通告无法由此插件完全控制。MAC 白名单不等同于设备身份认证。

配置保存在 `/etc/config/passipv6`，最近成功配置为
`/etc/passipv6/last-good.json`。设备轮询不写闪存，配置未变时重载也不重复写恢复备份。

## 开发与 CI

先阅读 [AGENTS.md](AGENTS.md)。Node.js 24 和 Python 3：

```sh
npm ci
npm test
python3 tests/static.py
```

安装脚本测试需要 Bash。原生策略测试使用 ucode：

```sh
ucode -L root/usr/share/ucode tests/policy.uc
```

原生辅助进程的协议测试需要 C 编译器和 libjson-c 开发头文件：

```sh
cc -D_GNU_SOURCE -Wall -Wextra -Werror -fsanitize=address,undefined tests/ra.c -ljson-c -o /tmp/passipv6-ra-test
/tmp/passipv6-ra-test
```

标准 LuCI 源码包可以放入 SDK 或固件源码树编译。使用本仓库的 SDK 构建辅助脚本：

```sh
PASSIPV6_SDK=/path/to/immortalwrt-sdk sh tools/build.sh
```

CI 对 main 和 PR 执行测试及构建；推送与 `PKG_VERSION` 一致的版本标签，例如
`1.1.0`，才发布 Release。正式 Release 不覆盖原有版本，修正后递增版本。
构建基线为官方 ImmortalWrt 25.12.1 SDK；依赖仅为原生运行时。
产物为主 APK、中文 APK、版本固定的安装脚本和 SHA256SUMS。

[VERIFICATION.md](VERIFICATION.md) 区分已经完成的验证与未覆盖的情况。
`tests/network.py` 与 `tests/lifecycle.py` 只能在隔离测试路由器中运行。
生命周期测试还要求显式设置 `PASSIPV6_TEST_VM=1`。

## English

PassIPV6 is a native LuCI IPv6 MAC allowlist under **Services → PassIPV6**.
Only selected LAN devices may use IPv6 through the router; IPv4 remains available.
The page supports English and Simplified Chinese, keyboard access and screen-reader announcements.

The installer above installs, upgrades or reinstalls the latest stable release while preserving
the existing allowlist. Use an IPv4 management connection: a first installation starts with an
empty allowlist. It requires x86/64 ImmortalWrt 25.12.1 or newer stable releases, the native LuCI,
ucode, ip-full and libjson-c runtime, and compatible nftables bridge/ingress filtering. Runtime checks
are mandatory; hardware offload and direct bridge-port flowtable offload are unsupported.

Version 1.1.0 delivers locally generated RAs to allowlisted Ethernet addresses and blocks their
original multicast copies, preserving the existing subnet, AP layout and odhcpd configuration.
The native helper is supervised by procd; application is confirmed only when filtering and RA
delivery agree. A helper failure keeps the multicast guard in place and is reported as an error.
RA relay/hybrid modes are unsupported. Reconnect affected devices once after upgrading or
changing permissions to refresh cached IPv6 routes and DNS. Real iOS acceptance is separate
from Linux packet tests and must not be assumed from a successful installation.

Old SLAAC and self-generated link-local addresses may remain. Other necessary multicast remains
available; downstream traffic that never reaches the router and MAC spoofing are outside this
control. Future firmware versions must retain the required APIs and pass preflight checks.
See Releases for the two packages, installer and checksums.

## License

[Apache License 2.0](LICENSE). Copyright 2026 PassIPV6 contributors.
