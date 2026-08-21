"""Config and options flows for VahaC Media Controller."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult, OptionsFlowWithReload
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er, selector

from .const import (
    CONF_AC_ENTITY,
    CONF_FAN_ENTITY,
    CONF_LIGHT_1_ENTITY,
    CONF_LIGHT_2_ENTITY,
    CONF_PLAYER_ENTITY,
    DOMAIN,
)
from .music_assistant import MUSIC_ASSISTANT_DOMAIN


def _config_schema() -> vol.Schema:
    """Build the shared Config Flow and Options Flow schema."""
    return vol.Schema(
        {
            vol.Required(CONF_PLAYER_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="media_player",
                    integration=MUSIC_ASSISTANT_DOMAIN,
                )
            ),
            vol.Optional(CONF_LIGHT_1_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="light")
            ),
            vol.Optional(CONF_LIGHT_2_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="light")
            ),
            vol.Optional(CONF_FAN_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
            vol.Optional(CONF_AC_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch")
            ),
        }
    )


def _clean_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """Drop empty optional selector values."""
    return {key: value for key, value in user_input.items() if value}


def _music_assistant_registry_entry(hass: Any, entity_id: str) -> Any | None:
    """Return the registry entry only when MA owns the selected player."""
    registry_entry = er.async_get(hass).async_get(entity_id)
    if registry_entry is None or registry_entry.platform != MUSIC_ASSISTANT_DOMAIN:
        return None
    return registry_entry


def _controller_unique_id(registry_entry: Any) -> str:
    """Build the stable controller ID for a Music Assistant player."""
    return f"music_assistant_player_{registry_entry.unique_id}"


def _entry_player_entity(entry: config_entries.ConfigEntry) -> str | None:
    """Return the effective Music Assistant player for an entry."""
    return entry.options.get(
        CONF_PLAYER_ENTITY,
        entry.data.get(CONF_PLAYER_ENTITY),
    )


class VahaCMediaControllerConfigFlow(
    config_entries.ConfigFlow,
    domain=DOMAIN,
):
    """Handle initial UI configuration."""

    VERSION = 1

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
                return self.async_create_entry(
                    title=f"Media Controller – {title}",
                    data=_clean_input(user_input),
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _config_schema(), user_input or {}
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> VahaCMediaControllerOptionsFlow:
        """Create the options flow."""
        return VahaCMediaControllerOptionsFlow()


class VahaCMediaControllerOptionsFlow(OptionsFlowWithReload):
    """Allow player and optional room-control remapping."""

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
                    return self.async_create_entry(
                        data=_clean_input(user_input)
                    )

        current = dict(self.config_entry.data)
        current.update(self.config_entry.options)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                _config_schema(), user_input or current
            ),
            errors=errors,
        )
