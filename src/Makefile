CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra
CPPFLAGS += -D_GNU_SOURCE
LDLIBS += -ljson-c

compile: passipv6-ra

passipv6-ra: ra.c
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) -o $@ $< $(LDLIBS)

install: compile
	install -d $(DESTDIR)/usr/libexec
	install -m 0755 passipv6-ra $(DESTDIR)/usr/libexec/passipv6-ra

clean:
	rm -f passipv6-ra

.PHONY: compile install clean
