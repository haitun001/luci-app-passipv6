# Verification

## 1.0.2

- Native uclient-fetch timed out connecting directly to GitHub on the reference
  router; curl fetched the same release URL successfully. The bootstrap and
  installer now prefer curl when available and set explicit download timeouts.
- Installer tests additionally exercise curl preference, the uclient-fetch path,
  and bootstrap cleanup without executing incomplete downloads.

## 1.0.1

- UI regression tests cover immediate save/apply announcements, backend confirmation,
  delayed and stale responses, reload recovery, cancellation, save/apply failures,
  timeouts, read-only permissions, keyboard focus and safe device-name rendering.
- Automated axe checks cover the relevant WCAG 2.2 AA structural rules. Browser
  contrast and narrow-screen checks were established on native bootstrap and
  Material themes in the development baseline; those scoped styles are retained.
- Installer fixtures cover first install, upgrade, same-version reinstall, preserving
  a populated allowlist, newer supported versions, incompatible targets, missing
  runtime dependencies, missing/duplicate checksums, corrupt downloads, failed
  preflight, solver failures, install failures and inactive policies.
- The candidate read-only preflight and policy tests passed on the reference
  ImmortalWrt 25.12.1 / Linux 6.12.94 router without applying rules.
- CI runs the source checks, UI and installer tests, builds both APKs with the
  ImmortalWrt SDK, and publishes checksummed assets only for version tags.
  See [workflow runs](https://github.com/haitun001/luci-app-passipv6/actions)
  and the [release](https://github.com/haitun001/luci-app-passipv6/releases/tag/1.0.1).

## Packet-filtering baseline

The filtering rules are unchanged from development version 1.0.0-r2. Its isolated
ImmortalWrt 25.12.1 / Linux 6.12.94 VM tests covered:

- IPv4 and IPv6 connectivity for allowed clients; IPv6 blocking for denied clients.
- A complete DHCPv6 Solicit/Advertise/Request/Reply exchange for an allowed client,
  and no offer reaching a denied client.
- Existing TCP/UDP flows with an actual conntrack OFFLOAD flag, followed by
  revocation blocking both directions while IPv4 and an allowed client remain live.
- Atomic rollback on an invalid nft transaction, repeated application and
  unchanged unrelated firewall tables.
- Invalid configuration recovery, concurrent reloads, firewall reload/restart,
  reboot recovery and uninstall.
- Native LuCI Save, Save & Apply, English/Chinese rendering, keyboard operation,
  320px layout and automated browser accessibility checks.

Production checks on that baseline compared unrelated configuration hashes,
firewall structures and existing service processes, and verified DNS and IPv4
HTTPS connectivity. Dynamic DNS set membership was allowed to change naturally.

## Limits

Automated accessibility checks do not replace a dedicated screen-reader audit.
Not every physical client or every future firmware has been tested. New firmware
must retain the required APIs and pass runtime checks. Hardware offload,
direct bridge-port flowtable offload, downstream-only communication and MAC
spoofing remain outside the supported guarantees.

Do not run disruptive lifecycle tests on production routers. Development
dependencies, SDKs, VM disks and staging files must be removed after local work;
source files, final packages and verification records may be retained.
