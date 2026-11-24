# Changelog

## 1.2.0

- 将 IPv6 白名单明确为路由访问权限，保留同一 LAN 设备之间的 IPv6 通信、组播发现和单播回复。
- 在 LAN 桥主设备入口及桥输出路径限制未授权路由流量，继续保护 RA、DHCPv6 和已有软件加速连接的撤权。
- 应用状态核对关键规则内容、hook、接口和端口集合；保持已有白名单、原子应用和辅助进程回退。
- 增加跨 LAN 桥端口的发现传输、邻居发现、地址冲突检测和组播加入回归测试；实际应用兼容性以验证记录为准。

- Preserve IPv6 communication and discovery between devices on the same LAN while restricting routed IPv6 access by MAC.
- Filter before software flow offload on the bridge master and block routed replies at bridge output; retain RA and DHCPv6 protection.
- Validate actual filtering expressions, hooks and interfaces before reporting an active policy. Existing configuration and rollback remain supported.
- Add packet regressions across separate LAN bridge ports. See the verification record for the tested application and hardware limits.

## 1.1.0

- 阻止原始组播路由通告，使用原生辅助进程按白名单 MAC 递送本机通告，保持现有网段、纯 AP 和 odhcpd 配置。
- 保留加速前入口与桥出口过滤；应用同时确认规则和通告递送进程，失败恢复上一策略，进程故障保持封锁并报告错误。
- 首次升级或修改权限后，受影响设备需断开并重连一次，以刷新旧 IPv6 路由和 DNS 状态。链路本地地址仍可能存在。
- 主 APK 包含原生程序，改为目标架构包；更新安装预检、生命周期测试及构建流程。
- 公开安装命令已完成实际路由器升级，保留原配置和白名单。参考用户确认 iPhone 重连后恢复正常；更多机型、iOS 版本和休眠唤醒场景尚未覆盖。

- Deliver native router advertisements to allowlisted Ethernet addresses while blocking their original multicast copies, without changing subnets, AP layout or odhcpd configuration.
- Confirm both packet filtering and RA delivery on apply, roll back failed applications, and keep filtering enforced when the helper fails.
- Reconnect affected clients once after upgrading or changing permissions to refresh cached IPv6 routes and DNS. Link-local addresses may remain.
- Build a native architecture-specific main APK and update installer preflight and lifecycle coverage.
- The published bootstrap upgraded the reference router while preserving its configuration and allowlist. The reference user confirmed normal iPhone connectivity after reconnecting; other models, iOS versions and sleep/wake scenarios remain unverified.

## 1.0.2

- 安装命令和脚本优先使用 curl，解决原生下载工具直连 GitHub 超时的情况；保留 uclient-fetch 支持，并设置下载超时。
- 补充两种下载工具和安装入口的失败清理测试。保留 1.0.1 的界面修复及升级、重复安装能力。

- Prefer curl in the bootstrap command and installer when available, with bounded download timeouts and native uclient-fetch support.
- Test both download tools and bootstrap failure cleanup. Includes the UI fixes and upgrade/reinstall support from 1.0.1.

## 1.0.1

- 修复保存并应用期间的读屏提示：保持明确的进行中状态，确认规则生效后再通报结果，忽略过期轮询响应。
- 精简中英文页面说明，仅介绍 IPv6 白名单功能。
- 增加只读兼容性检查、带校验的一键安装脚本，支持覆盖升级与保留白名单的同版本重装。
- 使用 Apache-2.0，增加自动构建和版本标签发布。

- Fix screen-reader announcements during Save & Apply, including delayed responses, reloads, cancellation and errors.
- Simplify English and Simplified Chinese page descriptions.
- Add runtime compatibility checks and a checksum-verified installer supporting upgrades and repeated installation while preserving the allowlist.
- Adopt Apache-2.0 and add CI builds and tag-triggered releases.
