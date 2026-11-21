# Verification

## 1.1.0

- Native C parser/configuration tests run with address and undefined-behavior
  sanitizers. UI regression checks include refusing application confirmation while
  RA delivery is unavailable and explaining the one-time client reconnect.
- The implementation keeps the original subnet/AP layout and odhcpd configuration.
  It blocks original multicast RAs and sends allowlisted copies through the same
  bridge so that destination filtering also applies to stale helper snapshots.
- Native packet tests passed on an isolated ImmortalWrt 25.12.1 / Linux 6.12.94 VM
  with two clients behind one pure-AP bridge and one shared router uplink. Only
  the allowed client received RA, PIO and RDNSS options and learned an RA default
  route. Renewals remained live across two router lifetimes. A stale helper
  snapshot could not deliver RAs to a removed MAC; reconnecting a denied client
  left it without an advertised default route or RDNSS option.
- The same run passed IPv4/IPv6 connectivity, actual DHCPv6 lease allocation,
  revocation of TCP/UDP with a real OFFLOAD conntrack flag, atomic transaction
  failure, repeated applies and unrelated table preservation.
- Native upgrade from 1.0.2 and same-version reinstall preserved the populated
  allowlist. Invalid configuration, concurrent reloads, firewall reload/restart,
  helper commit failure with rollback, altered guard detection, helper failure
  and procd recovery passed. Program file changes replaced the helper while
  preserving the policy. Reboot recovered active filtering and RA delivery.
- CI-built packages passed native reinstall with the populated allowlist intact.
  Uninstall removed the owned tables/include and left fw4 unchanged; reinstall
  after removal restored active filtering and RA delivery.
- Native Bootstrap LuCI passed page-scope axe WCAG 2.2 AA checks in English at
  1280px and Simplified Chinese at 320px, without horizontal overflow. Save-only
  retained the active policy; changed-selection Save & Apply confirmed the new
  allowlist after native reload. No-change apply immediately announced progress
  and then the active policy, without an intervening unsaved/save-only message.
- The published 1.1.0 bootstrap upgraded the reference router successfully.
  The populated allowlist, network/DHCP/firewall/proxy/ad-filter configuration
  hashes, unrelated nftables structure (excluding dynamic set members/counters)
  and all six tracked service PIDs were unchanged. IPv4 HTTPS and local DNS passed.
  Backend filtering, helper readiness and application confirmation were all true.
- Production counters recorded locally generated RAs being captured, allowlisted
  copies being sent, and original multicast RAs being dropped. These observations
  confirm router-side behavior; they do not prove a physical iOS client's state.
- The public Release contains both APKs, the version-pinned installer and checksums.
  Downloaded assets matched SHA256SUMS, and the public latest bootstrap matched
  the 1.1.0 installer. Both main and tag workflows passed.
- After deployment, the reference user reported that the affected, unselected
  iPhone returned to normal connectivity after one Wi-Fi reconnection. This
  evidence covers that user's reconnection/application check. The exact iOS
  version, resolver state, sleep/wake behavior and other physical clients were
  not independently recorded or tested.

## 1.0.2

- Native uclient-fetch timed out connecting directly to GitHub on the reference
  router; curl fetched the same release URL successfully. The bootstrap and
  installer now prefer curl when available and set explicit download timeouts.
- Installer tests additionally exercise curl preference, the uclient-fetch path,
  and bootstrap cleanup without executing incomplete downloads.
- The published one-line command successfully upgraded the reference router from
  1.0.0-r2 to 1.0.2-r1, then reinstalled the same version. Both runs preserved the
  populated allowlist and confirmed the active policy. Package checksums matched
  the [1.0.2 release](https://github.com/haitun001/luci-app-passipv6/releases/tag/1.0.2).
- Headless Chrome checked the installed Material-theme page in English at 1280px
  and Simplified Chinese at 320px. Both had zero page-scope axe WCAG 2.2 AA
  violations and no horizontal page overflow. No-change Save & Apply announced
  progress followed by the active policy, without unsaved or not-yet-applied
  announcements. Changed-selection and native apply-event paths have UI regression
  coverage; the live allowlist was not edited for these checks.
- The stock login page emitted an unauthenticated `uci/get` request for `luci`
  with Access denied; this also occurred when opening native Status Overview.
  Authenticated PassIPV6 checks had no page errors. The login-page issue is
  recorded separately and was not changed by this work.
- Before/after checks found unchanged network, DHCP, firewall, proxy and ad-filter
  configuration hashes, identical fw4 rules and unchanged proxy rule structure
  after excluding dynamic set members. All nine tracked service processes retained
  their PIDs and commands. DNS and IPv4 HTTPS checks passed.

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

Versions through 1.0.2 retained the filtering rules from 1.0.0-r2. Its isolated
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
