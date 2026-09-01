"""Config, options, and panel subentry flows for Media Controller."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlowWithReload,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er, selector

from .const import (
    CONF_PLAYER_ENTITY,
    CONF_PROFILE,
    CONF_SLOTS,
    DOMAIN,
    ENTRY_VERSION,
    SUBENTRY_TYPE_PANEL,
    slot_entity_key,
    slot_label_key,
)
from .music_assistant import MUSIC_ASSISTANT_DOMAIN
from .profiles import (
    CONTROLLER_PROFILE,
    PANEL_PROFILES,
    ClientProfile,
    panel_profile,
)
from .slots import (
    SlotConfig,
    slots_from_input,
    stored_slots,
    suggested_slot_values,
)

CONF_NAME = "name"


def _slot_fields(profile: ClientProfile) -> dict[Any, Any]:
    """Build one entity selector and one label field per slot.

    Every slot of the profile is shown, so the form states the device's real
    limit; an empty slot simply hides that tile.
    """
    fields: dict[Any, Any] = {}
    for spec in profile.slots:
        fields[vol.Optional(slot_entity_key(spec.index))] = (
            selector.EntitySelector(
                selector.EntitySelectorConfig(domain=list(spec.domains))
            )
        )
        fields[vol.Optional(slot_label_key(spec.index))] = (
            selector.TextSelector()
        )
    return fields


def _controller_schema() -> vol.Schema:
    """Build the shared Config Flow and Options Flow schema."""
    return vol.Schema(
        {
            vol.Required(CONF_PLAYER_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="media_player",
                    integration=MUSIC_ASSISTANT_DOMAIN,
                )
            ),
            **_slot_fields(CONTROLLER_PROFILE),
        }
    )


def _music_assistant_registry_entry(hass: Any, entity_id: str) -> Any | None:
    """Return the registry entry only when MA owns the selected player."""
    registry_entry = er.async_get(hass).async_get(entity_id)
    if registry_entry is None or registry_entry.platform != MUSIC_ASSISTANT_DOMAIN:
        return None
    return registry_entry


def _controller_unique_id(registry_entry: Any) -> str:
    """Build the stable controller ID for a Music Assistant player."""
    return f"music_assistant_player_{registry_entry.unique_id}"


def _entry_player_entity(entry: ConfigEntry) -> str | None:
    """Return the effective Music Assistant player for an entry."""
    return entry.options.get(
        CONF_PLAYER_ENTITY,
        entry.data.get(CONF_PLAYER_ENTITY),
    )


def _controller_slots(entry: ConfigEntry) -> list[SlotConfig]:
    """Return the ESP32 slots of a controller entry."""
    if CONF_SLOTS in entry.options:
        return stored_slots(entry.options, CONF_SLOTS)
    return stored_slots(entry.data, CONF_SLOTS)


def _stored_input(
    player_entity: str,
    slots: list[SlotConfig],
) -> dict[str, Any]:
    """Build the stored shape of a controller configuration."""
    return {
        CONF_PLAYER_ENTITY: player_entity,
        CONF_SLOTS: [slot.as_stored() for slot in slots],
    }


class MediaControllerConfigFlow(
    config_entries.ConfigFlow,
    domain=DOMAIN,
):
    """Handle initial UI configuration."""

    VERSION = ENTRY_VERSION

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Configure a controller from a Music Assistant player."""
        errors: dict[str, str] = {}
        if user_input is not None:
            player_entity = user_input[CONF_PLAYER_ENTITY]
            registry_entry = _music_assistant_registry_entry(
                self.hass, player_entity
            )
            if registry_entry is None:
                errors[CONF_PLAYER_ENTITY] = "not_music_assistant"
            else:
                await self.async_set_unique_id(
                    _controller_unique_id(registry_entry)
                )
                self._abort_if_unique_id_configured()
                state = self.hass.states.get(player_entity)
                title = state.name if state is not None else player_entity
                slots = slots_from_input(
                    self.hass, CONTROLLER_PROFILE, user_input
                )
                return self.async_create_entry(
                    title=f"Media Controller – {title}",
                    data=_stored_input(player_entity, slots),
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _controller_schema(), user_input or {}
            ),
            errors=errors,
            description_placeholders={
                "slot_count": str(CONTROLLER_PROFILE.slot_count),
                "profile": CONTROLLER_PROFILE.name,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> MediaControllerOptionsFlow:
        """Create the options flow."""
        return MediaControllerOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls,
        config_entry: ConfigEntry,
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Panels are added as subentries of a controller."""
        return {SUBENTRY_TYPE_PANEL: PanelSubentryFlow}


class MediaControllerOptionsFlow(OptionsFlowWithReload):
    """Allow player and ESP32 slot remapping."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Manage controller options and reload automatically."""
        errors: dict[str, str] = {}
        if user_input is not None:
            player_entity = user_input[CONF_PLAYER_ENTITY]
            registry_entry = _music_assistant_registry_entry(
                self.hass, player_entity
            )
            if registry_entry is None:
                errors[CONF_PLAYER_ENTITY] = "not_music_assistant"
            else:
                unique_id = _controller_unique_id(registry_entry)
                for entry in self.hass.config_entries.async_entries(DOMAIN):
                    if entry.entry_id == self.config_entry.entry_id:
                        continue
                    other_player = _entry_player_entity(entry)
                    other_registry_entry = (
                        _music_assistant_registry_entry(
                            self.hass, other_player
                        )
                        if other_player
                        else None
                    )
                    if (
                        entry.unique_id == unique_id
                        or other_registry_entry is not None
                        and _controller_unique_id(other_registry_entry)
                        == unique_id
                    ):
                        errors[CONF_PLAYER_ENTITY] = "already_configured"
                        break
                else:
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        unique_id=unique_id,
                    )
                    slots = slots_from_input(
                        self.hass,
                        CONTROLLER_PROFILE,
                        user_input,
                        _controller_slots(self.config_entry),
                    )
                    return self.async_create_entry(
                        data=_stored_input(player_entity, slots)
                    )

        current: dict[str, Any] = {
            CONF_PLAYER_ENTITY: _entry_player_entity(self.config_entry) or ""
        }
        current.update(suggested_slot_values(_controller_slots(self.config_entry)))
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                _controller_schema(), user_input or current
            ),
            errors=errors,
            description_placeholders={
                "slot_count": str(CONTROLLER_PROFILE.slot_count),
                "profile": CONTROLLER_PROFILE.name,
            },
        )


class PanelSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure one panel client of a controller."""

    _profile: ClientProfile = PANEL_PROFILES[0]
    _name: str = ""

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> SubentryFlowResult:
        """Pick the device type, which decides how many slots follow."""
        if user_input is not None:
            self._profile = panel_profile(user_input[CONF_PROFILE])
            self._name = str(user_input.get(CONF_NAME) or "").strip()
            return await self.async_step_slots()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PROFILE, default=PANEL_PROFILES[0].slug
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(
                                    value=profile.slug,
                                    label=(
                                        f"{profile.name} "
                                        f"({profile.slot_count} room controls)"
                                    ),
                                )
                                for profile in PANEL_PROFILES
                            ],
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Optional(CONF_NAME): selector.TextSelector(),
                }
            ),
        )

    async def async_step_slots(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> SubentryFlowResult:
        """Fill the slot form of the chosen device type."""
        if user_input is not None:
            slots = slots_from_input(self.hass, self._profile, user_input)
            return self.async_create_entry(
                title=self._name or self._profile.name,
                data={
                    CONF_PROFILE: self._profile.slug,
                    CONF_SLOTS: [slot.as_stored() for slot in slots],
                },
            )

        return self.async_show_form(
            step_id="slots",
            data_schema=vol.Schema(_slot_fields(self._profile)),
            description_placeholders={
                "profile": self._profile.name,
                "slot_count": str(self._profile.slot_count),
            },
        )

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> SubentryFlowResult:
        """Edit the slots of an existing panel.

        The device type is not offered again: changing it would change how many
        proxies exist and is a delete-and-add operation.
        """
        subentry = self._get_reconfigure_subentry()
        self._profile = panel_profile(subentry.data.get(CONF_PROFILE))
        current = stored_slots(subentry.data, CONF_SLOTS)

        if user_input is not None:
            slots = slots_from_input(
                self.hass, self._profile, user_input, current
            )
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                data={
                    CONF_PROFILE: self._profile.slug,
                    CONF_SLOTS: [slot.as_stored() for slot in slots],
                },
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_slot_fields(self._profile)),
                suggested_slot_values(current),
            ),
            description_placeholders={
                "profile": self._profile.name,
                "slot_count": str(self._profile.slot_count),
            },
        )
