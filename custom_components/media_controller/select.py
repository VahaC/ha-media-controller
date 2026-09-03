"""The two selects a panel owns: the page it is on, and the layout it draws.

They are the same platform and nothing else. The page is a reading with a
command behind it: the client reports where a person navigated, and accepts a
request to go elsewhere, which makes the panel addressable from an automation.
The skin is a setting: Home Assistant owns it, the client adopts it on its next
poll, and it therefore stays readable while the device is asleep.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .panel_entity import PanelEntity, async_store_settings
from .panel_state import PAGES, SETTING_PLAYER_SKIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the selects of one panel."""
    runtime = entry.runtime_data
    if not hasattr(runtime, "state"):
        return

    entities: list[SelectEntity] = [PanelPageSelect(entry, runtime)]
    # A client that draws one interface gets no skin selector: an entity whose
    # only option is the way things already look is a control that does
    # nothing. The options are the client's own names, so the tablet offers its
    # two and the ESP32 its three.
    if runtime.client.profile.skins:
        entities.append(PanelPlayerSkinSelect(entry, runtime))
    async_add_entities(entities)


class PanelPageSelect(PanelEntity, SelectEntity):
    """The page the panel is on."""

    _attr_options = list(PAGES)

    def __init__(self, entry: ConfigEntry, runtime: Any) -> None:
        """Initialize the page selector."""
        super().__init__(entry, runtime, "page")

    @property
    def available(self) -> bool:
        """Return whether the tablet has reported which page it is on."""
        return self._panel.is_online() and bool(self._panel.status.page)

    @property
    def current_option(self) -> str | None:
        """Return the page the panel last reported."""
        return self._panel.status.page or None

    async def async_select_option(self, option: str) -> None:
        """Ask the panel to show another page."""
        if not self._panel.request_page(option):
            raise ServiceValidationError(f"{option} is not a panel page")


class PanelPlayerSkinSelect(PanelEntity, SelectEntity):
    """Which of its layouts the panel draws.

    A setting rather than a command, so it is always available: it keeps its
    value while the device is asleep or being reflashed, and the client adopts
    it on its next poll without restarting anything.

    The options are the client's own names. On the tablet a skin is the whole
    interface, player page and room controls alike; on the ESP32 it is which of
    the three home layouts the firmware shows. Both are the same question to
    the person asking it, which is why they are one entity.
    """

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, runtime: Any) -> None:
        """Initialize the skin selector for this client's own layouts."""
        super().__init__(entry, runtime, "player_skin")
        self._client = runtime.client
        self._profile = runtime.client.profile
        self._attr_options = list(self._profile.skins)

    async def async_added_to_hass(self) -> None:
        """Tell the config sensor which entity holds the skin.

        A panel that lets a person pick a skin on the tablet itself calls
        `select.select_option` on this entity, so it has to learn the entity
        ID from somewhere. It is reported here, once Home Assistant has
        assigned one, rather than guessed from the device name: the panel
        keeps no entity ID of its own by design, and a guess would break the
        first time this entity or the config sensor was renamed.
        """
        await super().async_added_to_hass()
        self._client.async_set_skin_select_entity_id(self.entity_id)

    @property
    def current_option(self) -> str:
        """Return the layout Home Assistant has asked this client for.

        Until someone chooses, that is the client's own fallback — the first
        option, which is what every client starts from.
        """
        chosen = self._panel.settings.player_skin
        if self._profile.knows_skin(chosen):
            return chosen
        return self._profile.skins[0]

    async def async_select_option(self, option: str) -> None:
        """Store the new layout and let the client pick it up."""
        if not self._profile.knows_skin(option):
            raise ServiceValidationError(
                f"{option} is not a layout the {self._profile.name} draws"
            )
        settings = self._panel.set_setting(SETTING_PLAYER_SKIN, option)
        async_store_settings(self.hass, self._entry, settings)
