# Changelog

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
