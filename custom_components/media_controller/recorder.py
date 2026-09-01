"""Recorder exclusions for Media Controller sensors.

All three sensors carry their payload in attributes, because a Home Assistant
state is limited to 255 characters. None of it is history: the queue payload
alone is written on every track change and would grow the database for nothing.
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
        "slot_count",
        "slots",
        "revision",
        "player",
        "queue",
        "playlists",
    }
