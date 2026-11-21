/* SPDX-License-Identifier: Apache-2.0 */
#include <arpa/inet.h>
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <ifaddrs.h>
#include <json-c/json.h>
#include <linux/filter.h>
#include <linux/if_packet.h>
#include <net/ethernet.h>
#include <net/if.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

#define RUNDIR "/var/run/passipv6"
#define SOCKET RUNDIR "/ra.sock"
#define CANDIDATE RUNDIR "/ra-candidate.json"
#define ACTIVE RUNDIR "/ra-active.json"
#define MAX_JSON 131072
#define MAX_MACS 4096

struct policy {
	json_object *config;
	char bridge[IFNAMSIZ];
	unsigned int ifindex;
	uint8_t own_mac[6], mac[MAX_MACS][6];
	size_t count;
	int fd;
};

static volatile sig_atomic_t stopping;
static const char *delivery_error;
static uint64_t received, sent, invalid;

static void stop(int sig) { (void)sig; stopping = 1; }

static void dispose(struct policy *p)
{
	if (!p) return;
	if (p->fd >= 0) close(p->fd);
	json_object_put(p->config);
	free(p);
}

static bool mac_address(const char *s, uint8_t out[6])
{
	if (!s || strlen(s) != 17) return false;
	unsigned int any = 0;
	for (size_t i = 0; i < 6; i++) {
		if (!isxdigit((unsigned char)s[3*i]) || !isxdigit((unsigned char)s[3*i+1]) ||
		    (i < 5 && s[3*i+2] != ':')) return false;
		char byte[3] = { s[3*i], s[3*i+1], 0 };
		out[i] = strtoul(byte, NULL, 16);
		any |= out[i];
	}
	return any && !(out[0] & 1);
}

static json_object *parse_json(const char *s, size_t len)
{
	json_tokener *tok = json_tokener_new();
	if (!tok) return NULL;
	json_object *value = json_tokener_parse_ex(tok, s, len);
	size_t end = json_tokener_get_parse_end(tok);
	while (end < len && isspace((unsigned char)s[end])) end++;
	if (json_tokener_get_error(tok) != json_tokener_success || end != len ||
	    !json_object_is_type(value, json_type_object)) {
		json_object_put(value);
		value = NULL;
	}
	json_tokener_free(tok);
	return value;
}

static json_object *read_config(const char *path)
{
	FILE *f = path ? fopen(path, "r") : stdin;
	if (!f) return NULL;
	char *text = malloc(MAX_JSON + 1);
	if (!text) { if (path) fclose(f); return NULL; }
	size_t n = fread(text, 1, MAX_JSON + 1, f);
	bool ok = !ferror(f) && n <= MAX_JSON;
	if (path) fclose(f);
	json_object *value = ok ? parse_json(text, n) : NULL;
	free(text);
	return value;
}

static struct policy *policy_config(json_object *value)
{
	json_object *bridge, *macs, *generation;
	if (!value || !json_object_object_get_ex(value, "bridge", &bridge) ||
	    !json_object_is_type(bridge, json_type_string) ||
	    !json_object_object_get_ex(value, "mac", &macs) ||
	    !json_object_is_type(macs, json_type_array) ||
	    !json_object_object_get_ex(value, "generation", &generation) ||
	    !json_object_is_type(generation, json_type_int) ||
	    json_object_get_int64(generation) < 1) return NULL;
	const char *name = json_object_get_string(bridge);
	size_t len = json_object_get_string_len(bridge), count = json_object_array_length(macs);
	if (!len || len >= IFNAMSIZ || strlen(name) != len || count > MAX_MACS) return NULL;
	for (size_t i = 0; i < len; i++)
		if (!isalnum((unsigned char)name[i]) && !strchr("_.:-", name[i])) return NULL;
	struct policy *p = calloc(1, sizeof(*p));
	if (!p) return NULL;
	p->fd = -1;
	strcpy(p->bridge, name);
	p->count = count;
	for (size_t i = 0; i < count; i++) {
		json_object *mac = json_object_array_get_idx(macs, i);
		if (!json_object_is_type(mac, json_type_string) || json_object_get_string_len(mac) != 17 ||
		    !mac_address(json_object_get_string(mac), p->mac[i]) ||
		    (i && memcmp(p->mac[i-1], p->mac[i], 6) >= 0)) {
			dispose(p);
			return NULL;
		}
	}
	p->config = json_object_get(value);
	return p;
}

static bool link_ready(struct policy *p)
{
	struct ifreq req = { 0 };
	if (!p || p->fd < 0 || if_nametoindex(p->bridge) != p->ifindex) return false;
	strcpy(req.ifr_name, p->bridge);
	if (ioctl(p->fd, SIOCGIFFLAGS, &req) || !(req.ifr_flags & IFF_UP)) return false;
	if (ioctl(p->fd, SIOCGIFHWADDR, &req)) return false;
	return !memcmp(req.ifr_hwaddr.sa_data, p->own_mac, 6);
}

static bool open_capture(struct policy *p)
{
	char path[128];
	snprintf(path, sizeof(path), "/sys/class/net/%s/bridge", p->bridge);
	struct stat st;
	if (stat(path, &st) || !S_ISDIR(st.st_mode)) return false;
	p->ifindex = if_nametoindex(p->bridge);
	p->fd = socket(AF_PACKET, SOCK_RAW | SOCK_CLOEXEC | SOCK_NONBLOCK, htons(ETH_P_ALL));
	if (p->fd < 0 || !p->ifindex) return false;
	struct ifreq req = { 0 };
	strcpy(req.ifr_name, p->bridge);
	if (ioctl(p->fd, SIOCGIFHWADDR, &req)) return false;
	memcpy(p->own_mac, req.ifr_hwaddr.sa_data, 6);
	/* Packet taps run before bridge output filtering. Only native, unfragmented RAs are copied. */
	struct sock_filter instructions[] = {
		BPF_STMT(BPF_LD | BPF_H | BPF_ABS, 12),
		BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, ETH_P_IPV6, 0, 5),
		BPF_STMT(BPF_LD | BPF_B | BPF_ABS, 20),
		BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, IPPROTO_ICMPV6, 0, 3),
		BPF_STMT(BPF_LD | BPF_B | BPF_ABS, 54),
		BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 134, 0, 1),
		BPF_STMT(BPF_RET | BPF_K, 65590),
		BPF_STMT(BPF_RET | BPF_K, 0)
	};
	struct sock_fprog filter = { .len = sizeof(instructions)/sizeof(*instructions), .filter = instructions };
	int buffer = 262144;
	setsockopt(p->fd, SOL_SOCKET, SO_RCVBUF, &buffer, sizeof(buffer));
	struct sockaddr_ll addr = { .sll_family = AF_PACKET, .sll_protocol = htons(ETH_P_ALL), .sll_ifindex = p->ifindex };
	return !setsockopt(p->fd, SOL_SOCKET, SO_ATTACH_FILTER, &filter, sizeof(filter)) &&
		!bind(p->fd, (struct sockaddr *)&addr, sizeof(addr)) && link_ready(p);
}

static bool local_source(struct policy *p, const uint8_t address[16])
{
	struct ifaddrs *list;
	if (getifaddrs(&list)) return false;
	bool found = false;
	for (struct ifaddrs *i = list; i; i = i->ifa_next) {
		if (!i->ifa_addr || i->ifa_addr->sa_family != AF_INET6 || strcmp(i->ifa_name, p->bridge)) continue;
		struct sockaddr_in6 *s = (struct sockaddr_in6 *)i->ifa_addr;
		if (!memcmp(&s->sin6_addr, address, 16)) found = true;
	}
	freeifaddrs(list);
	return found;
}

static size_t valid_ra(uint8_t *frame, size_t len, const uint8_t own[6])
{
	static const uint8_t multicast_mac[6] = { 0x33, 0x33, 0, 0, 0, 1 };
	static const uint8_t all_nodes[16] = { 0xff, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1 };
	if (len < 70 || memcmp(frame, multicast_mac, 6) || memcmp(frame+6, own, 6) ||
	    frame[12] != 0x86 || frame[13] != 0xdd || (frame[14] >> 4) != 6 ||
	    frame[20] != IPPROTO_ICMPV6 || frame[21] != 255 ||
	    frame[22] != 0xfe || (frame[23] & 0xc0) != 0x80 || memcmp(frame+38, all_nodes, 16) ||
	    frame[54] != 134 || frame[55] != 0) return 0;
	size_t payload = (size_t)frame[18] * 256 + frame[19];
	if (payload < 16 || payload + 54 > len) return 0;
	for (size_t off = 70; off < payload + 54;) {
		if (off + 2 > payload + 54 || !frame[off+1]) return 0;
		off += (size_t)frame[off+1] * 8;
		if (off > payload + 54) return 0;
	}
	return payload + 54;
}

static void checksum(uint8_t *frame, size_t len)
{
	/* The outgoing tap may precede checksum offload; copies need a complete checksum. */
	frame[56] = frame[57] = 0;
	uint32_t sum = (len - 54) + IPPROTO_ICMPV6;
	for (size_t i = 22; i < len; i += 2)
		sum += (uint32_t)frame[i] * 256 + (i + 1 < len ? frame[i+1] : 0);
	while (sum >> 16) sum = (sum & 0xffff) + (sum >> 16);
	sum = (~sum) & 0xffff;
	frame[56] = sum >> 8;
	frame[57] = sum;
}

static void forward_ra(struct policy *p)
{
	uint8_t frame[65590];
	struct sockaddr_ll addr;
	socklen_t alen = sizeof(addr);
	ssize_t n = recvfrom(p->fd, frame, sizeof(frame), MSG_DONTWAIT, (struct sockaddr *)&addr, &alen);
	if (n < 0 || addr.sll_pkttype != PACKET_OUTGOING || addr.sll_ifindex != (int)p->ifindex) return;
	/* Unicast copies, including our own, must never be fanned out again. */
	if (n >= 6 && !(frame[0] & 1)) return;
	size_t len = valid_ra(frame, n, p->own_mac);
	if (!len || !local_source(p, frame+22)) { invalid++; return; }
	received++;
	if (!link_ready(p)) { delivery_error = "Managed bridge changed; reapply the policy"; return; }
	checksum(frame, len);
	struct sockaddr_ll target = { .sll_family = AF_PACKET, .sll_protocol = htons(ETH_P_IPV6),
		.sll_ifindex = p->ifindex, .sll_halen = ETH_ALEN };
	for (size_t i = 0; i < p->count; i++) {
		memcpy(frame, p->mac[i], 6);
		memcpy(target.sll_addr, p->mac[i], 6);
		if (sendto(p->fd, frame, len, MSG_DONTWAIT | MSG_NOSIGNAL,
		           (struct sockaddr *)&target, sizeof(target)) != (ssize_t)len) {
			delivery_error = "Router advertisement delivery failed";
			return;
		}
		sent++;
	}
	delivery_error = NULL;
}

static json_object *reply(bool success, const char *error)
{
	json_object *r = json_object_new_object();
	json_object_object_add(r, "success", json_object_new_boolean(success));
	if (error) json_object_object_add(r, "error", json_object_new_string(error));
	return r;
}

static json_object *request(json_object *msg, struct policy **active, struct policy **pending)
{
	json_object *command;
	if (!msg || !json_object_object_get_ex(msg, "command", &command) ||
	    !json_object_is_type(command, json_type_string)) return reply(false, "Invalid request");
	const char *cmd = json_object_get_string(command);
	if (!strcmp(cmd, "prepare") || !strcmp(cmd, "restore")) {
		json_object *config = NULL;
		json_object_object_get_ex(msg, "config", &config);
		struct policy *p = policy_config(config);
		if (!p || !open_capture(p)) { dispose(p); return reply(false, "RA capture is unavailable on the managed bridge"); }
		if (!strcmp(cmd, "restore")) {
			dispose(*active); *active = p;
			delivery_error = NULL;
			dispose(*pending); *pending = NULL;
		} else {
			dispose(*pending); *pending = p;
		}
	} else if (!strcmp(cmd, "commit")) {
		if (!*pending || !link_ready(*pending)) return reply(false, "No prepared RA policy");
		/* Queued advertisements belong to the previous policy and may contain old lifetimes. */
		uint8_t discard[65590];
		for (int i = 0; ; i++) {
			if (recv((*pending)->fd, discard, sizeof(discard), MSG_DONTWAIT) < 0) break;
			if (i == 4095) return reply(false, "RA capture queue is busy; retry application");
		}
		dispose(*active); *active = *pending; *pending = NULL;
		delivery_error = NULL;
	} else if (!strcmp(cmd, "abort")) {
		dispose(*pending); *pending = NULL;
	} else if (!strcmp(cmd, "clear")) {
		dispose(*active); *active = NULL;
		dispose(*pending); *pending = NULL;
		delivery_error = NULL;
	} else if (!strcmp(cmd, "status")) {
		json_object *r = reply(true, delivery_error);
		json_object_object_add(r, "ready", json_object_new_boolean(link_ready(*active) && !delivery_error));
		if (*active) json_object_object_add(r, "config", json_object_get((*active)->config));
		json_object_object_add(r, "received", json_object_new_int64(received));
		json_object_object_add(r, "sent", json_object_new_int64(sent));
		json_object_object_add(r, "invalid", json_object_new_int64(invalid));
		return r;
	} else return reply(false, "Unknown command");
	return reply(true, NULL);
}

static int connect_control(void)
{
	int fd = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
	struct sockaddr_un addr = { .sun_family = AF_UNIX };
	strcpy(addr.sun_path, SOCKET);
	struct timeval timeout = { .tv_sec = 2 };
	if (fd < 0) return -1;
	setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
	setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
	if (!connect(fd, (struct sockaddr *)&addr, sizeof(addr))) return fd;
	close(fd);
	return -1;
}

static int control(const char *cmd)
{
	int fd = -1;
	for (int retry = 0; retry < (!strcmp(cmd, "prepare") ? 50 : 1); retry++) {
		fd = connect_control();
		if (fd >= 0) break;
		usleep(100000);
	}
	if (fd < 0) { puts("{\"success\":false,\"error\":\"RA service is unavailable\"}"); return 1; }
	json_object *msg = json_object_new_object();
	json_object_object_add(msg, "command", json_object_new_string(cmd));
	if (!strcmp(cmd, "prepare") || !strcmp(cmd, "restore")) {
		json_object *config = read_config(!strcmp(cmd, "prepare") ? CANDIDATE : ACTIVE);
		if (!config) { json_object_put(msg); close(fd); return 1; }
		json_object_object_add(msg, "config", config);
	}
	const char *data = json_object_to_json_string_ext(msg, JSON_C_TO_STRING_PLAIN);
	size_t len = strlen(data);
	char *response = malloc(MAX_JSON + 1);
	ssize_t n = -1;
	if (response && send(fd, data, len, MSG_NOSIGNAL) == (ssize_t)len)
		n = recv(fd, response, MAX_JSON + 1, MSG_TRUNC);
	json_object *r = n > 0 && n <= MAX_JSON ? parse_json(response, n) : NULL, *success;
	bool ok = r && json_object_object_get_ex(r, "success", &success) && json_object_get_boolean(success);
	if (r) puts(json_object_to_json_string_ext(r, JSON_C_TO_STRING_PLAIN));
	else puts("{\"success\":false,\"error\":\"RA service did not acknowledge the request\"}");
	json_object_put(r); json_object_put(msg); free(response); close(fd);
	return ok ? 0 : 1;
}

static int daemon_main(void)
{
	mkdir(RUNDIR, 0700);
	int lock = open(RUNDIR "/ra.lock", O_CREAT | O_RDWR | O_CLOEXEC, 0600);
	if (lock < 0 || flock(lock, LOCK_EX | LOCK_NB)) return 1;
	int server = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
	struct sockaddr_un addr = { .sun_family = AF_UNIX };
	strcpy(addr.sun_path, SOCKET);
	unlink(SOCKET);
	if (server < 0 || bind(server, (struct sockaddr *)&addr, sizeof(addr)) ||
	    chmod(SOCKET, 0600) || listen(server, 8)) return 1;
	struct policy *active = NULL, *pending = NULL;
	json_object *saved = read_config(ACTIVE);
	active = policy_config(saved);
	json_object_put(saved);
	if (active && !open_capture(active)) { dispose(active); active = NULL; }
	signal(SIGTERM, stop); signal(SIGINT, stop); signal(SIGPIPE, SIG_IGN);
	char *buffer = malloc(MAX_JSON + 1);
	if (!buffer) return 1;
	while (!stopping) {
		struct pollfd fds[2] = { { server, POLLIN, 0 }, { active ? active->fd : -1, POLLIN, 0 } };
		if (poll(fds, 2, 1000) < 0) { if (errno == EINTR) continue; break; }
		/* Handle policy changes before reading any packet under the old policy. */
		if (fds[0].revents & POLLIN) {
			int peer = accept4(server, NULL, NULL, SOCK_CLOEXEC);
			if (peer < 0) continue;
			struct ucred cred;
			socklen_t clen = sizeof(cred);
			struct timeval timeout = { .tv_sec = 1 };
			setsockopt(peer, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
			setsockopt(peer, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
			if (!getsockopt(peer, SOL_SOCKET, SO_PEERCRED, &cred, &clen) && cred.uid == 0) {
				ssize_t n = recv(peer, buffer, MAX_JSON + 1, MSG_TRUNC);
				json_object *msg = n > 0 && n <= MAX_JSON ? parse_json(buffer, n) : NULL;
				json_object *r = request(msg, &active, &pending);
				const char *data = json_object_to_json_string_ext(r, JSON_C_TO_STRING_PLAIN);
				send(peer, data, strlen(data), MSG_NOSIGNAL);
				json_object_put(msg); json_object_put(r);
			}
			close(peer);
			continue;
		}
		if (active && (fds[1].revents & POLLIN)) forward_ra(active);
		if (active && (fds[1].revents & (POLLERR | POLLHUP | POLLNVAL))) {
			delivery_error = "RA capture stopped; reapply the policy";
			close(active->fd); active->fd = -1;
		}
	}
	dispose(active); dispose(pending); free(buffer);
	unlink(SOCKET); close(server); close(lock);
	return 0;
}

int main(int argc, char **argv)
{
	umask(077);
	if (argc != 2 || geteuid()) return 2;
	if (!strcmp(argv[1], "daemon")) return daemon_main();
	if (!strcmp(argv[1], "check")) {
		json_object *value = read_config(NULL);
		struct policy *p = policy_config(value);
		bool ok = p && open_capture(p);
		dispose(p); json_object_put(value);
		if (!ok) fputs("RA capture is unavailable on the managed bridge\n", stderr);
		return ok ? 0 : 1;
	}
	if (!strcmp(argv[1], "prepare") || !strcmp(argv[1], "commit") || !strcmp(argv[1], "abort") ||
	    !strcmp(argv[1], "restore") || !strcmp(argv[1], "clear") || !strcmp(argv[1], "status"))
		return control(argv[1]);
	return 2;
}
