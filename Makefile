# Installs Play it Slowly; packages call this with DESTDIR, PREFIX and, where their Python path differs, PYTHONDIR.

PREFIX ?= /usr/local
DESTDIR ?=
PYTHON ?= python3
PYTHONDIR ?= $(shell $(PYTHON) -c 'import sysconfig; print(sysconfig.get_path("purelib", vars={"base": "$(PREFIX)"}))')
VERSION := $(shell sed -n 's/^VERSION = "\(.*\)"/\1/p' playitslowly/app.py)

APP_ID = ch.x29a.playitslowly
BINDIR = $(DESTDIR)$(PREFIX)/bin
DATADIR = $(DESTDIR)$(PREFIX)/share

.PHONY: all install uninstall dist

all:

install:
	install -d $(DESTDIR)$(PYTHONDIR)/playitslowly
	install -m 644 playitslowly/*.py $(DESTDIR)$(PYTHONDIR)/playitslowly/
	install -D -m 755 bin/playitslowly $(BINDIR)/playitslowly
	install -D -m 644 share/applications/$(APP_ID).desktop $(DATADIR)/applications/$(APP_ID).desktop
	install -D -m 644 share/metainfo/$(APP_ID).metainfo.xml $(DATADIR)/metainfo/$(APP_ID).metainfo.xml
	install -D -m 644 share/icons/hicolor/32x32/apps/$(APP_ID).png $(DATADIR)/icons/hicolor/32x32/apps/$(APP_ID).png
	install -D -m 644 share/icons/hicolor/128x128/apps/$(APP_ID).png $(DATADIR)/icons/hicolor/128x128/apps/$(APP_ID).png
	install -D -m 644 share/icons/hicolor/scalable/apps/$(APP_ID).svg $(DATADIR)/icons/hicolor/scalable/apps/$(APP_ID).svg

uninstall:
	rm -rf $(DESTDIR)$(PYTHONDIR)/playitslowly
	rm -f $(BINDIR)/playitslowly
	rm -f $(DATADIR)/applications/$(APP_ID).desktop
	rm -f $(DATADIR)/metainfo/$(APP_ID).metainfo.xml
	rm -f $(DATADIR)/icons/hicolor/32x32/apps/$(APP_ID).png
	rm -f $(DATADIR)/icons/hicolor/128x128/apps/$(APP_ID).png
	rm -f $(DATADIR)/icons/hicolor/scalable/apps/$(APP_ID).svg

# A source tarball of the committed tree, which the rpm spec builds from.
dist:
	git archive --format=tar.gz --prefix=playitslowly-$(VERSION)/ -o playitslowly-$(VERSION).tar.gz HEAD
