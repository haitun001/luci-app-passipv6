# PassIPV6 development contract

## Intent

Develop a native LuCI IPv6 MAC allowlist. Preserve existing device configuration
during deployments. Never store credentials or private deployment details in this
public repository, artifacts, logs, or documentation.

The accepted policy retains SLAAC compatibility: unlisted clients cannot use IPv6
through this router or obtain DHCPv6 leases. They may still display SLAAC and
link-local addresses. Traffic switched entirely downstream is outside this control.
Initial policy is enabled with an empty allowlist. IPv4 remains available.

## Confirmed target

- ImmortalWrt 25.12.1, x86/64, Linux 6.12.94, apk, nftables 1.1.6, firewall4.
- The reference topology is logical network `lan` and bridge `br-lan` with Ethernet
  members. Derive names from UCI and sysfs, never hardcode a deployment's ports.
- Preserve the existing odhcpd RA/SLAAC and DHCPv6 settings.
- Software flow offload is enabled on br-lan and WAN devices; hardware offload is
  disabled. LAN bridge ports are not registered directly in the flowtable.
- Passwall, passwall-ai-ipv6-fix, adblock-fast, dnsmasq and miniupnpd coexist.
- Native inet ingress and bridge hooks work. netdev egress and bridge metadata
  expressions `ibrname`/`obrname` fail on this kernel. Use ordinary port names.
- Package feed kernel ABI may differ from a running kernel. Never force-install
  kernel modules or upgrade firmware for this plugin.

## Rules that must remain true

- Own only `inet passipv6` and `bridge passipv6`, the passipv6 UCI package, and the
  explicitly named firewall include `passipv6`. Never flush the global ruleset,
  change other tables, NAT, marks, DNS, DHCP or offload settings.
- Filter IPv6 only. Whitelisted traffic continues through existing firewall and
  service rules. Preserve essential IPv6 multicast for compatible SLAAC clients.
- LAN ingress filtering must precede flow offload; bridge egress filtering blocks
  replies to removed MACs. Do not replace this with a normal forward-chain rule.
- Validate the actual offload path. Hardware offload or directly offloaded bridge
  ports require an explicit unsupported-state error, not a silent security downgrade.
- Apply both tables in one nft transaction after `nft --check`. Serialize writers.
  Failure retains the active rules. Keep a validated last-good policy for recovery.
- Ordinary Save & Apply reloads only this service. The fw4 include must not reload
  fw4 or unrelated services, avoiding recursion and lock-order deadlocks.
- Do not reboot the live router or restart Passwall/adblock-fast for testing.
  Exercise disruptive lifecycle scenarios in an isolated environment first.
- RPC permissions are limited to plugin configuration, read-only queries and a
  fixed, argument-free reapply method for retrying failed applications.
  Validate MACs server-side; never interpolate untrusted input into shell commands.
- Do not synchronously call another rpcd object from a ucode RPC handler: it blocks
  rpcd's event loop. Device names from luci-rpc are queried separately by the UI;
  DHCP leases, neighbors and FDB membership are scoped on the backend.
- ucode functions must be declared before callers; they are not JS-style hoisted.
- LuCI E() emits `disabled="false"` for boolean false. Use null for enabled controls.
- Device refresh must preserve unsaved choices and focus. Use native LuCI styling,
  semantic controls, keyboard access and WCAG 2.2 AA checks. English source strings
  and Simplified Chinese translations must stay in sync.
- Save & Apply must announce progress immediately and confirm the actual policy;
  do not announce Save-only or unsaved messages during that operation. Ignore stale
  poll responses and retain pending application state across LuCI's native reload.
- Keep service compatibility details in technical documentation, not page copy.
- Public releases use Apache-2.0 and increasing semantic versions. The release tag
  matches PKG_VERSION; never overwrite an already published release.
- Installer support starts at stable ImmortalWrt 25.12.1, without a numeric upper
  bound, subject to runtime checks. x86/64 is the validated installation target.
- Use APK's local-package reinstall support. Never uninstall to upgrade or reset
  the existing allowlist. CI artifacts must include both APKs and checksums.

## Development and verification

The source root is a standard LuCI package. Keep runtime dependencies native.
Track meaningful protocol, transaction, discovery and UI tests under `tests/`.
Update this file and README as implementation and verification become concrete.
Do not report `nft --check` as proof of actual packet filtering. Record separately
syntax checks, isolated packet tests and production checks; disclose untested cases.

References:
- https://github.com/immortalwrt/immortalwrt/blob/openwrt-25.12/package/network/config/firewall4/Makefile
- https://wiki.nftables.org/wiki-nftables/index.php/Atomic_rule_replacement
- https://docs.kernel.org/networking/nf_flowtable.html

## Verification baseline

- The development baseline is 1.0.0-r2; 1.0.1-r1 adds application-state feedback,
  installer preflight and public CI releases. Preserve live allowlists on updates.
- Version 1.0.2-r1 prefers curl when available, with bounded download timeouts;
  verify both downloader paths and the published bootstrap command.
- Native packet tests passed in an isolated ImmortalWrt 25.12.1 / 6.12.94 VM:
  IPv4/IPv6, actual DHCPv6 lease allocation, revoking offloaded TCP/UDP, failed
  transactions, repeated applies and unrelated table preservation.
- Native LuCI Save / Save & Apply, device RPC, firewall reload/restart, concurrent
  applies, invalid-config recovery, reboot recovery and uninstall were verified.
- Production configuration hashes, fw4 rules and pre-existing service PIDs were
  unchanged. Passwall structure was unchanged; live DNS set members naturally varied.
- Material-theme buttons require the scoped contrast overrides in the page. Native
  bootstrap and production Material were checked with axe; no page-scope violations.
- Read VERIFICATION.md for the exact evidence and remaining verification limits.
- Cleanup requirement: retain source, final APKs and verification documents;
  remove SDKs, VM disks, task-only build dependencies and remote staging after work.
