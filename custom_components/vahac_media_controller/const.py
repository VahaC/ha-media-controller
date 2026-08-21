"""Constants for the VahaC Media Controller integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "vahac_media_controller"

PLATFORMS: list[Platform] = [Platform.LIGHT, Platform.SENSOR, Platform.SWITCH]

CONF_PLAYER_ENTITY = "player_entity"
CONF_LIGHT_1_ENTITY = "light_1_entity"
CONF_LIGHT_2_ENTITY = "light_2_entity"
CONF_FAN_ENTITY = "fan_entity"
CONF_AC_ENTITY = "ac_entity"

CONFIG_ENTITY_KEYS = (
    CONF_PLAYER_ENTITY,
    CONF_LIGHT_1_ENTITY,
    CONF_LIGHT_2_ENTITY,
    CONF_FAN_ENTITY,
    CONF_AC_ENTITY,
)

DEFAULT_PLAYLIST_LIMIT = 50
DEFAULT_QUEUE_WINDOW_BEFORE = 5
DEFAULT_QUEUE_WINDOW_SIZE = 50
QUEUE_REFRESH_DELAY = 3.0
PLAYLIST_REFRESH_INTERVAL = timedelta(hours=6)

SERVICE_REFRESH = "refresh"
SERVICE_PLAY_QUEUE_ITEM = "play_queue_item"

ATTR_ENTRY_ID = "entry_id"
ATTR_ENTITY_ID = "entity_id"
ATTR_QUEUE_ITEM_ID = "queue_item_id"
