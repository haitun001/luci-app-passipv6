/* SPDX-License-Identifier: Apache-2.0 */
#define main passipv6_ra_main
#include "../src/ra.c"
#undef main
#include <assert.h>

int main(void)
{
	uint8_t own[6] = { 2, 0, 0, 0, 0, 1 }, packet[102] = { 0 }, copy[102];
	memcpy(packet, (uint8_t[]){ 0x33, 0x33, 0, 0, 0, 1 }, 6);
	memcpy(packet+6, own, 6);
	packet[12] = 0x86; packet[13] = 0xdd; packet[14] = 0x60;
	packet[19] = 48; packet[20] = 58; packet[21] = 255;
	packet[22] = 0xfe; packet[23] = 0x80; packet[37] = 1;
	packet[38] = 0xff; packet[39] = 2; packet[53] = 1;
	packet[54] = 134; packet[70] = 3; packet[71] = 4;
	assert(valid_ra(packet, sizeof(packet), own) == sizeof(packet));
	for (size_t len = 0; len < sizeof(packet); len++) assert(!valid_ra(packet, len, own));
	const size_t offsets[] = { 0, 6, 12, 14, 19, 20, 21, 22, 38, 53, 54, 55, 71 };
	for (size_t i = 0; i < sizeof(offsets)/sizeof(*offsets); i++) {
		memcpy(copy, packet, sizeof(copy)); copy[offsets[i]] = 0;
		if (offsets[i] == 55) copy[55] = 1;
		assert(!valid_ra(copy, sizeof(copy), own));
	}
	memcpy(copy, packet, sizeof(copy)); copy[20] = 44;
	assert(!valid_ra(copy, sizeof(copy), own));
	memcpy(copy, packet, sizeof(copy)); memcpy(copy, own, 6);
	assert(!valid_ra(copy, sizeof(copy), own));
	const char *good = "{\"bridge\":\"br-test\",\"mac\":[\"02:00:00:00:00:01\"],\"generation\":1}";
	json_object *j = parse_json(good, strlen(good));
	struct policy *p = policy_config(j);
	assert(p && p->count == 1 && p->fd == -1);
	dispose(p); json_object_put(j);
	const char *bad[] = {
		"{}", "{\"bridge\":\"br-test;id\",\"mac\":[],\"generation\":1}",
		"{\"bridge\":\"br-test\",\"mac\":[\"ff:ff:ff:ff:ff:ff\"],\"generation\":1}",
		"{\"bridge\":\"br-test\",\"mac\":[\"00:00:00:00:00:00\"],\"generation\":1}",
		"{\"bridge\":\"br-test\",\"mac\":[\"02:00:00:00:00:01\",\"02:00:00:00:00:01\"],\"generation\":1}",
		"{\"bridge\":\"br-test\",\"mac\":[],\"generation\":0}",
		"{\"bridge\":\"br-test\\u0000bad\",\"mac\":[],\"generation\":1}"
	};
	for (size_t i = 0; i < sizeof(bad)/sizeof(*bad); i++) {
		j = parse_json(bad[i], strlen(bad[i])); assert(!policy_config(j)); json_object_put(j);
	}
	assert(!parse_json("{}junk", 6));
	assert(!parse_json("[]", 2));
	puts("PASS: RA frame boundaries, multicast loop prevention and helper configuration validation");
	return 0;
}
