#!/usr/bin/ucode

import * as policy from 'passipv6';

try {
	if (ARGV[0] == 'reload') policy.reload();
	else if (ARGV[0] == 'check') policy.check(ARGV[1]);
	else if (ARGV[0] == 'remove') policy.remove();
	else die('Unsupported operation');
} catch (e) {
	warn('PassIPV6: ' + e.message + '\n');
	exit(1);
}
