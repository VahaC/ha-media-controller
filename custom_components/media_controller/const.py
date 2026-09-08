"""Constants for the Media Controller integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "media_controller"

# A source owns the config sensor and the two Music Assistant sensors, and
# nothing else. Sensor first: it creates the controller device that every
# panel device references as its via_device.
PLATFORMS: list[Platform] = [Platform.SENSOR]

# A panel is a device with a display, a theme, and settings of its own, so it
# carries entities a source has no equivalent for.
PANEL_PLATFORMS: list[Platform] = [
    *PLATFORMS,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.TEXT,
    Platform.UPDATE,
]

ENTRY_VERSION = 4

# Version 2 titled every source "Media Controller – <player>". The prefix said
# nothing the integration page does not already say and made a source read like
# one more device, so version 3 drops it. Kept here because the migration has
# to recognise exactly the titles this integration wrote, and leave a title the
# user has since edited alone.
LEGACY_TITLE_PREFIX = "Media Controller – "

# One domain, two kinds of config entry. A controller is bound to a Music
# Assistant player; a panel is a client device that reads one controller.
# Entries written before panels existed carry no type and are controllers.
CONF_ENTRY_TYPE = "entry_type"
ENTRY_TYPE_CONTROLLER = "controller"
ENTRY_TYPE_PANEL = "panel"

CONF_PLAYER_ENTITY = "player_entity"

# Contract version 9 removed room-control slots along with the classic
# firmware that was their only reader. The key survives here because an entry
# written before that still carries the block, and the migration has to know
# what to delete.
CONF_SLOTS = "slots"
CONF_PROFILE = "profile"

# A panel's entity registry. The keys inside one stored record belong to the
# on-disk format and live in registry.py.
CONF_ENTITIES = "entities"
# The rids of registry elements that have been deleted. A device keys its own
# grid layout on a rid, so one is never handed out a second time.
CONF_RETIRED_RIDS = "retired_rids"

# Panel entries.
CONF_PANEL_ID = "panel_id"
CONF_CONTROLLER_ENTRY_ID = "controller_entry_id"
CONF_HOST = "host"
CONF_NAME = "name"
# The port a panel serves its own provisioning endpoint on, from the discovery
# record. Zero — which is what the T560 tablet advertises, because it serves
# nothing — means Home Assistant waits to be polled instead of pushing.
CONF_PANEL_PORT = "panel_port"
DEFAULT_PANEL_PORT = 80
# Where Home Assistant is, as it should be given to a panel. Stored only when
# Home Assistant could not work one out itself and somebody typed it; normally
# the answer comes from the network helpers on every delivery, so a Home
# Assistant that moves does not strand a panel with a stale address.
CONF_HA_URL = "ha_url"
# The tablet-local settings Home Assistant owns, stored on the panel entry.
# They are entry data rather than options: they are changed from entities, one
# value at a time, and must not reload the entry or restart the tablet.
CONF_PANEL_SETTINGS = "panel_settings"
# The colours and opacities a panel draws its player page with, stored beside
# the settings and for the same reason: they are changed from entities, one
# value at a time, and must not reload the entry or restart the panel.
CONF_PANEL_THEME = "panel_theme"

# Where a new ESP32-S3 panel is installed from: a browser, a USB cable, and
# no ESPHome. It is here rather than in strings.json because Home Assistant
# refuses a literal URL in a translation — a translator would otherwise have to
# carry it through every language, and an address that moved would have to be
# found in all of them. Every string that names it takes it as a placeholder.
INSTALLER_URL = "https://vahac.github.io/ha-media-controller/"

# A panel announces itself on the local network with this service type. It is
# deliberately not T560-specific: the profile travels as a TXT record, so a
# second kind of panel needs no second service type.
ZEROCONF_TYPE = "_media-controller._tcp.local."
ZEROCONF_PROP_PANEL_ID = "panel_id"
ZEROCONF_PROP_PROFILE = "profile"
ZEROCONF_PROP_NAME = "name"

# What a panel needs to be handed once, and what revokes it again.
CONF_PAIRING_CODE = "pairing_code"
CONF_REFRESH_TOKEN_ID = "refresh_token_id"
CONF_USER_ID = "user_id"

# hass.data layout.
DATA_RUNTIMES = "runtimes"
DATA_CONTROLLER_ENTITIES = "controller_entities"
DATA_PROVISIONING = "provisioning"
# Panel state by panel ID. The status endpoint is not tied to a config entry,
# so it resolves a reporting panel through this.
DATA_PANELS = "panels"
# The saved grid of every panel that has ever pushed one, by panel ID. It is
# deliberately not on a config entry: a layout has to outlive the entry, and
# writing it to entry data would reload the entry and rebuild the config
# sensor at the moment the panel saved a layout. See panel_layout.py.
DATA_LAYOUTS = "layouts"
# What the installer site publishes, and the verified images taken from it.
# One per installation, shared by every panel: two panels moving to the same
# build download it once. See panel_firmware.py.
DATA_FIRMWARE = "firmware"

# Version 1 keys. They survive only in async_migrate_entry.
CONF_LIGHT_1_ENTITY = "light_1_entity"
CONF_LIGHT_2_ENTITY = "light_2_entity"
CONF_FAN_ENTITY = "fan_entity"
CONF_AC_ENTITY = "ac_entity"

# Slot index, version 1 config key, and the domain the proxy was created in.
# Version 4 deletes all four; they are named here so that the migration can
# find the entity-registry rows they left behind, which is the only thing they
# are still good for.
LEGACY_SLOTS: tuple[tuple[int, str, str], ...] = (
    (1, CONF_LIGHT_1_ENTITY, "light"),
    (2, CONF_LIGHT_2_ENTITY, "light"),
    (3, CONF_FAN_ENTITY, "switch"),
    (4, CONF_AC_ENTITY, "switch"),
)

DEFAULT_PLAYLIST_LIMIT = 500
PLAYLIST_PAGE_SIZE = 100
DEFAULT_QUEUE_WINDOW_BEFORE = 5
DEFAULT_QUEUE_WINDOW_SIZE = 50
QUEUE_REFRESH_DELAY = 3.0
PLAYLIST_REFRESH_INTERVAL = timedelta(hours=6)
# How often the released firmware index is re-read. A firmware release is a
# rare event and the answer is a file on a public page, so this is deliberately
# unhurried: an installation should not be making a request an hour to find
# out that nothing has changed since last month.
FIRMWARE_INDEX_INTERVAL = timedelta(hours=6)

SERVICE_REFRESH = "refresh"
SERVICE_PLAY_QUEUE_ITEM = "play_queue_item"

ATTR_ENTRY_ID = "entry_id"
ATTR_ENTITY_ID = "entity_id"
ATTR_QUEUE_ITEM_ID = "queue_item_id"


def slot_unique_id(owner_id: str, index: int) -> str:
    """Return the unique ID one removed slot proxy was registered under.

    Nothing creates a proxy any more. This survives so that the version 4
    migration can find the rows the ones that existed left in the entity
    registry and delete them, rather than leaving a permanently unavailable
    `light.<source>_slot_1` behind for the life of the installation.
    """
    return f"{owner_id}_slot_{index}"


def panel_unique_id(panel_id: str) -> str:
    """Return the config-entry unique ID of one panel device."""
    return f"panel_{panel_id}"


def panel_entity_unique_id(entry_id: str, key: str) -> str:
    """Return the unique ID of one of a panel's own entities."""
    return f"{entry_id}_{key}"
