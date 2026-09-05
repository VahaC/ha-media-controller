"""The one route the on-device layout editor may write a card through.

```text
POST /api/media_controller/panel_card/<panel_id>
{"rid": "a3f1c92d", "name": "Настільна лампа", "icon": "desk-lamp"}
```

A panel serves a small layout editor on the device itself, with no
authentication of its own — see `media_controller_grid.h` for why that is a
decision rather than an oversight. The whole of that decision rests on the
device API being too narrow to be worth reaching: there is no route that reads
a state, calls a service, or names an entity the device does not already draw.

This endpoint is the Home Assistant end of the same rule, and it is written to
be boring in exactly the same way:

* **it changes one element of one panel's registry, and nothing else.** The
  `rid` must already be in *that* panel's registry. There is no path here that
  creates an element, deletes one, points one at a different entity, or
  touches any other config entry;
* **it never renames a Home Assistant entity.** The name is the label on a
  tile. `light.desk_lamp` keeps its own name, its own entity ID and its own
  registry row, and a person who wants those changed changes them where Home
  Assistant keeps them;
* **the icon is a catalog identifier or nothing.** No URL, no path, no upload:
  the editor may pick from what `icon_catalog` publishes and may pick nothing,
  and there is no third option;
* **the ownership check is the status endpoint's,** unchanged. A panel
  presents the token it was handed when it paired and Home Assistant accepts
  the request only from the Home Assistant user created for *that* panel. One
  panel cannot rename another's cards.

The registry is written back to whichever half of the config entry it already
lives in, and the loaded panel is told in place rather than reloaded: reloading
would recreate every entity the panel owns and make the device re-read a
layout that did not change, for a name somebody typed into a text box.
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ENTITIES
from .icon_catalog import is_known_icon
from .registry import (
    NAME_OK,
    RegistryEntry,
    apply_card_appearance,
    find_entry,
    normalize_name,
    stored_entries,
)
from .status import (
    STATUS_UNKNOWN_PANEL,
    STATUS_WRONG_PANEL,
    async_resolve_panel,
)

_LOGGER = logging.getLogger(__name__)

CARD_URL = "/api/media_controller/panel_card/{panel_id}"

STATUS_OK = "ok"
STATUS_INVALID_REQUEST = "invalid_request"
STATUS_UNKNOWN_ELEMENT = "unknown_element"
STATUS_UNKNOWN_ICON = "unknown_icon"


class PanelCardView(HomeAssistantView):
    """Rename one registry element of one panel, and choose its icon."""

    url = CARD_URL
    name = "api:media_controller:panel_card"

    def __init__(self, hass: HomeAssistant) -> None:
        """Hold the objects a request needs; there is one view per setup."""
        self._hass = hass

    def _refuse(self, error: str) -> web.Response:
        """Turn a failed ownership check into the answer it deserves."""
        if error == STATUS_WRONG_PANEL:
            return self.json({"status": STATUS_WRONG_PANEL}, status_code=403)
        return self.json({"status": STATUS_UNKNOWN_PANEL}, status_code=404)

    async def post(
        self,
        request: web.Request,
        panel_id: str,
    ) -> web.Response:
        """Apply one card's display name and icon."""
        registration, error = async_resolve_panel(
            self._hass, request, panel_id
        )
        if error is not None or registration is None:
            return self._refuse(error or STATUS_UNKNOWN_PANEL)

        try:
            payload: Any = await request.json()
        except ValueError:
            return self.json(
                {"status": STATUS_INVALID_REQUEST}, status_code=400
            )
        if not isinstance(payload, dict):
            return self.json(
                {"status": STATUS_INVALID_REQUEST}, status_code=400
            )

        rid = str(payload.get("rid") or "").strip()
        if not rid:
            return self.json(
                {"status": STATUS_INVALID_REQUEST}, status_code=400
            )

        # An absent key means "leave this alone"; a present one means "set it
        # to this, including to nothing". That is the difference between an
        # editor that only touched the name and one that cleared the icon.
        name: str | None = None
        if "name" in payload:
            name, failure = normalize_name(payload.get("name"))
            if failure != NAME_OK:
                return self.json({"status": failure}, status_code=400)

        icon: str | None = None
        if "icon" in payload:
            raw_icon = payload.get("icon")
            icon = "" if raw_icon is None else str(raw_icon).strip()
            # An unknown identifier is refused rather than quietly stored as
            # automatic: the editor picked it from a list this integration
            # published, so a value that is not on that list means the two
            # sides disagree and the person should be told.
            if icon and not is_known_icon(icon):
                return self.json(
                    {"status": STATUS_UNKNOWN_ICON}, status_code=400
                )

        if name is None and icon is None:
            return self.json(
                {"status": STATUS_INVALID_REQUEST}, status_code=400
            )

        entry = self._hass.config_entries.async_get_entry(
            registration.entry_id
        )
        if entry is None:
            return self.json(
                {"status": STATUS_UNKNOWN_PANEL}, status_code=404
            )

        section, stored = _registry_section(entry)
        if find_entry(stored, rid) is None:
            return self.json(
                {"status": STATUS_UNKNOWN_ELEMENT}, status_code=404
            )

        updated, changed = apply_card_appearance(
            stored, rid, name=name, icon=icon
        )
        if changed:
            self._async_store(entry, section, updated)
            # The loaded panel is told in place. Without this the payload
            # would not change until something else happened to reload the
            # entry, and the person editing the grid would watch a device
            # keep drawing the name they just replaced.
            runtime = getattr(entry, "runtime_data", None)
            client = getattr(runtime, "client", None)
            if client is not None:
                client.async_set_entries(updated)
            _LOGGER.debug(
                "Panel %s changed the appearance of element %s",
                panel_id,
                rid,
            )

        applied = find_entry(updated, rid)
        return self.json(
            {
                "status": STATUS_OK,
                "rid": rid,
                # Echoed so the editor can show what was actually stored
                # rather than what it hoped would be: an empty name is the
                # entity's own name coming back, which is a different answer
                # from the one the field was holding.
                "name": applied.name if applied is not None else "",
                "icon": applied.icon if applied is not None else "",
            }
        )

    def _async_store(
        self,
        entry: ConfigEntry,
        section: str,
        entries: list[RegistryEntry],
    ) -> None:
        """Write the registry back where this entry already keeps it.

        Options and data are not interchangeable here: the options flow writes
        the registry to options, and an entry that has never been through it
        still carries the one it was created with in data. Writing to the
        other half would leave two registries on disk with the older one
        winning on the next reload.

        Neither write reloads the entry. `async_update_entry` calls an entry's
        update listeners and nothing else, and this integration registers
        none: a reload is asked for explicitly, by the options flow, which is
        the one place that wants one. That is what makes this safe to call
        from an endpoint a person is typing into — a reload here would
        recreate every entity the panel owns and make the device re-read a
        layout that did not change, for one word in a text box.
        """
        stored = [element.as_stored() for element in entries]
        if section == "options":
            self._hass.config_entries.async_update_entry(
                entry, options={**entry.options, CONF_ENTITIES: stored}
            )
            return
        self._hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_ENTITIES: stored}
        )


def _registry_section(
    entry: ConfigEntry,
) -> tuple[str, list[RegistryEntry]]:
    """Return which half of the entry holds the registry, and what is in it."""
    if CONF_ENTITIES in entry.options:
        return "options", stored_entries(entry.options, CONF_ENTITIES)
    return "data", stored_entries(entry.data, CONF_ENTITIES)


def async_setup_card_endpoint(hass: HomeAssistant) -> None:
    """Register the card-appearance endpoint."""
    hass.http.register_view(PanelCardView(hass))
