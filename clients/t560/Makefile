PREFIX ?= /usr
CC ?= cc
PKG_CONFIG ?= pkg-config
PYTHON ?= python3

PACKAGES = gtk+-3.0 libsoup-3.0 json-glib-1.0
TARGET = t560-panel
TEST_TARGET = tests/test-json-helpers
RESOURCE_XML = data/t560.gresource.xml
RESOURCE_FILES = data/icons/light-1.png \
		 data/icons/light-2.png \
		 data/icons/fan.png \
		 data/icons/ac.png \
		 data/icons/desk-lamp.png \
		 data/icons/desk-led-strip.png
RESOURCE_SOURCE = build/t560-resources.c
ICON_NAME = t560-music-panel
ICON_SIZES = 16 24 32 48 64 128 256 512
SOURCES = src/main.c \
	  src/application.c \
	  src/app_config.c \
	  src/home_assistant_client.c \
	  src/json_helpers.c \
	  src/panel_ui.c \
	  src/system_status.c \
	  $(RESOURCE_SOURCE)
OBJECTS = $(SOURCES:.c=.o)
DEPFILES = $(OBJECTS:.o=.d)
TEST_OBJECTS = tests/test_json_helpers.o src/json_helpers.o
TEST_DEPFILES = tests/test_json_helpers.d

CPPFLAGS += -Isrc $(shell $(PKG_CONFIG) --cflags $(PACKAGES))
CFLAGS ?= -Os
CFLAGS += -std=c11 -Wall -Wextra -Wpedantic -Wformat=2 \
	  -Wstrict-prototypes -Wmissing-prototypes
LDLIBS += $(shell $(PKG_CONFIG) --libs $(PACKAGES))

.PHONY: all clean install test

all: $(TARGET)

$(TARGET): $(OBJECTS)
	$(CC) $(LDFLAGS) -o $@ $(OBJECTS) $(LDLIBS)

src/%.o: src/%.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -MMD -MP -c -o $@ $<

$(RESOURCE_SOURCE): $(RESOURCE_XML) $(RESOURCE_FILES)
	mkdir -p build
	glib-compile-resources --generate-source --target=$@ \
		--sourcedir=data $(RESOURCE_XML)

build/%.o: build/%.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -Wno-overlength-strings \
		-MMD -MP -c -o $@ $<

tests/%.o: tests/%.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -MMD -MP -c -o $@ $<

$(TEST_TARGET): $(TEST_OBJECTS)
	$(CC) $(LDFLAGS) -o $@ $(TEST_OBJECTS) $(LDLIBS)

test: $(TEST_TARGET)
	./$(TEST_TARGET)
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py'

clean:
	rm -f $(TARGET) $(OBJECTS) $(DEPFILES) tests/*.o tests/*.d $(TEST_TARGET)
	rm -f $(RESOURCE_SOURCE)
	rmdir build 2>/dev/null || true

install: t560-panel
	install -Dm755 t560-panel "$(DESTDIR)$(PREFIX)/bin/t560-panel"
	install -Dm755 scripts/t560-panel-watchdog "$(DESTDIR)$(PREFIX)/bin/t560-panel-watchdog"
	install -Dm755 scripts/t560-open-panel "$(DESTDIR)$(PREFIX)/bin/t560-open-panel"
	install -Dm755 scripts/t560-restart-panel "$(DESTDIR)$(PREFIX)/bin/t560-restart-panel"
	install -Dm755 scripts/t560-power-button.py "$(DESTDIR)$(PREFIX)/bin/t560-power-button.py"
	install -Dm755 scripts/t560-motion-detector.py "$(DESTDIR)$(PREFIX)/bin/t560-motion-detector.py"
	install -Dm755 scripts/t560-home-button "$(DESTDIR)$(PREFIX)/bin/t560-home-button"
	install -Dm755 scripts/t560-configure-openbox.py "$(DESTDIR)$(PREFIX)/bin/t560-configure-openbox.py"
	install -Dm644 config/config.ini.example "$(DESTDIR)/etc/t560-music-panel/config.ini.example"
	install -Dm644 data/t560-music-panel.desktop "$(DESTDIR)$(PREFIX)/share/applications/t560-music-panel.desktop"
	for size in $(ICON_SIZES); do \
		install -Dm644 \
			"data/icons/hicolor/$${size}x$${size}/apps/$(ICON_NAME).png" \
			"$(DESTDIR)$(PREFIX)/share/icons/hicolor/$${size}x$${size}/apps/$(ICON_NAME).png"; \
	done

-include $(DEPFILES) $(TEST_DEPFILES)
