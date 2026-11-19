include $(TOPDIR)/rules.mk

LUCI_NAME:=luci-app-passipv6
LUCI_TITLE:=IPv6 MAC allowlist
LUCI_DEPENDS:=+luci-base +rpcd-mod-ucode +ucode-mod-fs +ucode-mod-uci +ucode-mod-ubus +firewall4 +ip-full
LUCI_PKGARCH:=all
PKG_VERSION:=1.0.2
PKG_RELEASE:=1
PKG_PO_VERSION:=$(PKG_VERSION)-r$(PKG_RELEASE)
PKG_LICENSE:=Apache-2.0

define Package/luci-app-passipv6/conffiles
/etc/config/passipv6
/etc/passipv6/last-good.json
endef

define Package/luci-app-passipv6/prerm
#!/bin/sh
if [ -z "$$IPKG_INSTROOT" ]; then
    /etc/init.d/passipv6 disable
    /usr/libexec/passipv6 remove || exit 1
fi
exit 0
endef

include $(TOPDIR)/feeds/luci/luci.mk

# call BuildPackage - required by the OpenWrt package scanner.
