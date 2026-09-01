"""Config and options flows for Media Controller.

Two kinds of entry live in this domain. A **controller** is bound to a Music
Assistant player and owns the queue and playlist sensors and the four ESP32
slots. A **panel** is a client device — a tablet — that reads one controller;
it is normally created by discovery, when the panel announces itself on the
local network.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er, selector
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import (
    CONF_CONTROLLER_ENTRY_ID,
    CONF_PAIRING_CODE,
    CONF_REFRESH_TOKEN_ID,
    CONF_USER_ID,
    DATA_PROVISIONING,
    CONF_ENTRY_TYPE,
    CONF_HOST,
    CONF_NAME,
    CONF_PANEL_ID,
    CONF_PLAYER_ENTITY,
    CONF_PROFILE,
    CONF_SLOTS,
    DOMAIN,
    ENTRY_TYPE_CONTROLLER,
    ENTRY_TYPE_PANEL,
    ENTRY_VERSION,
    ZEROCONF_PROP_NAME,
    ZEROCONF_PROP_PANEL_ID,
    ZEROCONF_PROP_PROFILE,
    panel_unique_id,
    slot_entity_key,
    slot_label_key,
)
from .entries import controller_entries, is_panel_entry
from .music_assistant import MUSIC_ASSISTANT_DOMAIN
from .pairing import PairingStore, is_valid_code
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
from .tokens import async_create_panel_token, async_revoke_panel_token

_LOGGER = logging.getLogger(__name__)


def _pairings(hass: Any) -> PairingStore:
    """Return the store of approved pairings."""
    return hass.data.setdefault(DOMAIN, {}).setdefault(
        DATA_PROVISIONING, PairingStore()
    )


def _pairing_schema() -> vol.Schema:
    """Ask for the code the panel is showing on its own screen."""
    return vol.Schema(
        {
            vol.Required(CONF_PAIRING_CODE): selector.TextSelector(),
        }
    )


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


def _controller_selector(hass: Any) -> selector.SelectSelector:
    """Offer the controllers a panel can be attached to."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(
                    value=entry.entry_id, label=entry.title
                )
                for entry in controller_entries(hass)
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
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


def _stored_controller(
    player_entity: str,
    slots: list[SlotConfig],
) -> dict[str, Any]:
    """Build the stored shape of a controller configuration."""
    return {
        CONF_ENTRY_TYPE: ENTRY_TYPE_CONTROLLER,
        CONF_PLAYER_ENTITY: player_entity,
        CONF_SLOTS: [slot.as_stored() for slot in slots],
    }


class MediaControllerConfigFlow(
    config_entries.ConfigFlow,
    domain=DOMAIN,
):
    """Handle controller setup and panel discovery."""

    VERSION = ENTRY_VERSION

    _profile: ClientProfile = PANEL_PROFILES[0]
    _panel_id: str = ""
    _panel_name: str = ""
    _panel_host: str = ""
    _controller_entry_id: str = ""
    _slots: list[dict[str, Any]] = []

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Ask what is being added.

        Panels normally arrive through discovery; this path exists for a panel
        that cannot announce itself, and for adding a controller.
        """
        return self.async_show_menu(
            step_id="user",
            menu_options=["controller", "panel"],
        )

    # ---------------------------------------------------------------- controller

    async def async_step_controller(
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
                    data=_stored_controller(player_entity, slots),
                )

        return self.async_show_form(
            step_id="controller",
            data_schema=self.add_suggested_values_to_schema(
                _controller_schema(), user_input or {}
            ),
            errors=errors,
            description_placeholders={
                "slot_count": str(CONTROLLER_PROFILE.slot_count),
                "profile": CONTROLLER_PROFILE.name,
            },
        )

    # --------------------------------------------------------------------- panel

    async def async_step_zeroconf(
        self,
        discovery_info: ZeroconfServiceInfo,
    ) -> ConfigFlowResult:
        """Handle a panel that announced itself on the local network."""
        properties = discovery_info.properties or {}
        panel_id = str(properties.get(ZEROCONF_PROP_PANEL_ID) or "").strip()
        if not panel_id:
            return self.async_abort(reason="no_panel_id")

        await self.async_set_unique_id(panel_unique_id(panel_id))
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: discovery_info.host}
        )

        self._panel_id = panel_id
        self._profile = panel_profile(
            str(properties.get(ZEROCONF_PROP_PROFILE) or "")
        )
        self._panel_name = (
            str(properties.get(ZEROCONF_PROP_NAME) or "").strip()
            or panel_id
        )
        self._panel_host = discovery_info.host

        # Shown on the discovery card in the UI.
        self.context["title_placeholders"] = {
            "name": self._panel_name,
            "profile": self._profile.name,
        }
        return await self.async_step_panel_confirm()

    async def async_step_panel(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Add a panel by hand, for a device that cannot announce itself."""
        if not controller_entries(self.hass):
            return self.async_abort(reason="no_controller")

        if user_input is not None:
            self._profile = panel_profile(user_input[CONF_PROFILE])
            self._panel_id = user_input[CONF_PANEL_ID].strip().lower()
            self._panel_name = (
                str(user_input.get(CONF_NAME) or "").strip() or self._panel_id
            )
            self._controller_entry_id = user_input[CONF_CONTROLLER_ENTRY_ID]
            await self.async_set_unique_id(panel_unique_id(self._panel_id))
            self._abort_if_unique_id_configured()
            return await self.async_step_slots()

        return self.async_show_form(
            step_id="panel",
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
                    vol.Required(CONF_PANEL_ID): selector.TextSelector(),
                    vol.Optional(CONF_NAME): selector.TextSelector(),
                    vol.Required(
                        CONF_CONTROLLER_ENTRY_ID
                    ): _controller_selector(self.hass),
                }
            ),
        )

    async def async_step_panel_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Confirm a discovered panel and attach it to a controller."""
        controllers = controller_entries(self.hass)
        if not controllers:
            return self.async_abort(reason="no_controller")

        if user_input is not None:
            self._controller_entry_id = user_input[CONF_CONTROLLER_ENTRY_ID]
            return await self.async_step_slots()

        default = controllers[0].entry_id
        return self.async_show_form(
            step_id="panel_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CONTROLLER_ENTRY_ID, default=default
                    ): _controller_selector(self.hass),
                }
            ),
            description_placeholders={
                "name": self._panel_name,
                "profile": self._profile.name,
                "slot_count": str(self._profile.slot_count),
                "host": self._panel_host or "unknown",
            },
        )

    async def async_step_slots(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Fill the room-control slots of the panel being added."""
        if user_input is not None:
            self._slots = [
                slot.as_stored()
                for slot in slots_from_input(
                    self.hass, self._profile, user_input
                )
            ]
            return await self.async_step_provision()

        return self.async_show_form(
            step_id="slots",
            data_schema=vol.Schema(_slot_fields(self._profile)),
            description_placeholders={
                "name": self._panel_name,
                "profile": self._profile.name,
                "slot_count": str(self._profile.slot_count),
            },
        )

    async def async_step_provision(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Hand the panel a token of its own.

        The panel shows the code; nothing is typed on the tablet, and the
        token never travels over SSH.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            code = str(user_input[CONF_PAIRING_CODE]).strip()
            if not is_valid_code(code):
                errors[CONF_PAIRING_CODE] = "invalid_code"
            else:
                try:
                    token, refresh_token_id, user_id = (
                        await async_create_panel_token(
                            self.hass, self._panel_name or self._panel_id
                        )
                    )
                except Exception:  # noqa: BLE001 - surfaced as a form error
                    _LOGGER.exception("Could not create a token for the panel")
                    errors["base"] = "token_failed"
                else:
                    _pairings(self.hass).arm(self._panel_id, code, token)
                    return self.async_create_entry(
                        title=self._panel_name or self._profile.name,
                        data={
                            CONF_ENTRY_TYPE: ENTRY_TYPE_PANEL,
                            CONF_PROFILE: self._profile.slug,
                            CONF_PANEL_ID: self._panel_id,
                            CONF_NAME: self._panel_name,
                            CONF_HOST: self._panel_host,
                            CONF_CONTROLLER_ENTRY_ID: (
                                self._controller_entry_id
                            ),
                            CONF_REFRESH_TOKEN_ID: refresh_token_id,
                            CONF_USER_ID: user_id,
                            CONF_SLOTS: self._slots,
                        },
                    )

        return self.async_show_form(
            step_id="provision",
            data_schema=_pairing_schema(),
            errors=errors,
            description_placeholders={"name": self._panel_name},
        )

    # ---------------------------------------------------------------- re-pairing

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],
    ) -> ConfigFlowResult:
        """A configured panel lost its token and is asking for a new one."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Replace a panel's token without touching its configuration.

        Reinstalling the application keeps the token file, so this is only
        reached by a tablet that was wiped. Its device, its slots, and every
        entity ID stay exactly as they were.
        """
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            code = str(user_input[CONF_PAIRING_CODE]).strip()
            if not is_valid_code(code):
                errors[CONF_PAIRING_CODE] = "invalid_code"
            else:
                panel_id = entry.data.get(CONF_PANEL_ID, "")
                try:
                    token, refresh_token_id, user_id = (
                        await async_create_panel_token(
                            self.hass, entry.title or panel_id
                        )
                    )
                except Exception:  # noqa: BLE001 - surfaced as a form error
                    _LOGGER.exception("Could not create a token for the panel")
                    errors["base"] = "token_failed"
                else:
                    # The old token is revoked only once the new one exists,
                    # so a failure above cannot leave the panel with neither.
                    await async_revoke_panel_token(
                        self.hass,
                        entry.data.get(CONF_USER_ID),
                        entry.data.get(CONF_REFRESH_TOKEN_ID),
                    )
                    _pairings(self.hass).arm(panel_id, code, token)
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={
                            CONF_REFRESH_TOKEN_ID: refresh_token_id,
                            CONF_USER_ID: user_id,
                        },
                    )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_pairing_schema(),
            errors=errors,
            description_placeholders={"name": entry.title},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow that matches the entry kind."""
        if is_panel_entry(config_entry):
            return PanelOptionsFlow()
        return MediaControllerOptionsFlow()


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
                for entry in controller_entries(self.hass):
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
                        data={
                            CONF_PLAYER_ENTITY: player_entity,
                            CONF_SLOTS: [
                                slot.as_stored() for slot in slots
                            ],
                        }
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


class PanelOptionsFlow(OptionsFlowWithReload):
    """Edit the room-control slots of one panel.

    The device type is not offered again: it decides how many proxies exist,
    so changing it is a delete-and-add operation.
    """

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Options always start here; the panel form has its own step."""
        return await self.async_step_slots(user_input)

    async def async_step_slots(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Remap the panel's slots and reload automatically."""
        entry = self.config_entry
        profile = panel_profile(entry.data.get(CONF_PROFILE))
        current = (
            stored_slots(entry.options, CONF_SLOTS)
            if CONF_SLOTS in entry.options
            else stored_slots(entry.data, CONF_SLOTS)
        )

        if user_input is not None:
            slots = slots_from_input(self.hass, profile, user_input, current)
            return self.async_create_entry(
                data={CONF_SLOTS: [slot.as_stored() for slot in slots]}
            )

        return self.async_show_form(
            step_id="slots",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_slot_fields(profile)),
                suggested_slot_values(current),
            ),
            description_placeholders={
                "name": entry.title,
                "profile": profile.name,
                "slot_count": str(profile.slot_count),
            },
        )
