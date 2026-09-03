"""Constants for the Media Controller integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "media_controller"

# Sensor first: it creates the controller device that every panel device
# references as its via_device.
PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.LIGHT, Platform.SWITCH]

# A panel is a device with a battery, a display, and settings of its own, so
# it carries entities the ESP32 controller has no equivalent for.
PANEL_PLATFORMS: list[Platform] = [
    *PLATFORMS,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
]

ENTRY_VERSION = 3

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

# Room-control slots. See docs/ROOM_SLOTS.md. The keys inside one stored slot
# record belong to the on-disk format and live in transformations.py.
# Only a controller entry carries these; a panel carries a registry instead.
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
# The tablet-local settings Home Assistant owns, stored on the panel entry.
# They are entry data rather than options: they are changed from entities, one
# value at a time, and must not reload the entry or restart the tablet.
CONF_PANEL_SETTINGS = "panel_settings"

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

# Version 1 keys. They survive only in async_migrate_entry.
CONF_LIGHT_1_ENTITY = "light_1_entity"
CONF_LIGHT_2_ENTITY = "light_2_entity"
CONF_FAN_ENTITY = "fan_entity"
CONF_AC_ENTITY = "ac_entity"

# Slot index, version 1 config key, and the domain the proxy was created in.
# The domain cannot be re-derived from the target: a version 1 target may have
# been removed from Home Assistant since.
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

SERVICE_REFRESH = "refresh"
SERVICE_PLAY_QUEUE_ITEM = "play_queue_item"

ATTR_ENTRY_ID = "entry_id"
ATTR_ENTITY_ID = "entity_id"
ATTR_QUEUE_ITEM_ID = "queue_item_id"


def slot_entity_key(index: int) -> str:
    """Return the config-flow field name holding a slot target."""
    return f"slot_{index}_entity"


def slot_label_key(index: int) -> str:
    """Return the config-flow field name holding a slot label."""
    return f"slot_{index}_label"


def registry_name_key(rid: str) -> str:
    """Return the config-flow field name holding one element's label."""
    return f"name_{rid}"


# The multi-entity selector one registry group form is built around. Every
# group uses the same field name: only one group is ever on screen at a time.
CONF_GROUP_ENTITIES = "group_entities"


def slot_translation_key(index: int) -> str:
    """Return the entity translation key of a slot proxy."""
    return f"slot_{index}"


def slot_unique_id(owner_id: str, index: int) -> str:
    """Return the proxy unique ID for one slot of one client."""
    return f"{owner_id}_slot_{index}"


def panel_unique_id(panel_id: str) -> str:
    """Return the config-entry unique ID of one panel device."""
    return f"panel_{panel_id}"


def panel_entity_unique_id(entry_id: str, key: str) -> str:
    """Return the unique ID of one of a panel's own entities."""
    return f"{entry_id}_{key}"
