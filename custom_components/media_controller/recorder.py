"""Recorder exclusions for Media Controller sensors.

All three sensors carry their payload in attributes, because a Home Assistant
state is limited to 255 characters. None of it is history: the queue payload
alone is written on every track change and would grow the database for nothing,
and a panel's room states move every time anything in the house is switched.

This covers attributes only. A whole entity can be kept out of the recorder
only from the recorder's own configuration, which is the user's; the one
entity here worth excluding that way is the reset-reason sensor, and
docs/INTEGRATION.md says so rather than pretending the integration can do it.
"""

from __future__ import annotations

from homeassistant.core import HomeAssistant, callback


@callback
def exclude_attributes(hass: HomeAssistant) -> set[str]:
    """Return attributes that must never be stored in the database."""
    return {
        # Queue sensor.
        "data",
        # Playlist sensor.
        "names",
        "uris",
        # Config sensor.
        "profile",
        "revision",
        "contract_version",
        "player",
        "queue",
        "playlists",
        "settings",
        "commands",
        "theme",
        "entity_limit",
        "entities",
        "skin_select",
        "room_states",
    }
