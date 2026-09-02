"""Config and options flows for Media Controller.

Two kinds of entry live in this domain. A **controller** is bound to a Music
Assistant player and owns the queue and playlist sensors and the four ESP32
slots. A **panel** is a client device — a tablet — that reads one controller;
it is normally created by discovery, when the panel announces itself on the
local network.

A panel is paired first and configured afterwards. The tablet is the one part
of the setup that can fail on its own — it may be off, on another network, or
showing a code from an older attempt — so the flow settles that before asking
anyone to map room controls. Nothing is stored until the panel has answered
with the code it is showing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResultType
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
from .pairing import (
    PAIRING_TIMEOUT,
    STATE_COLLECTED,
    STATE_CONFIRMED,
    STATE_REJECTED,
    PairingStore,
    is_valid_code,
)
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

# How often the flow looks at the pairing store while it waits. The panel
# polls every three seconds, so this only decides how quickly the form moves
# on once it has.
PAIRING_POLL_INTERVAL = 1.0


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


def _pairing_errors(error: str | None) -> dict[str, str]:
    """Place a pairing failure on the field the person can act on."""
    if error is None:
        return {}
    if error == "token_failed":
        return {"base": error}
    return {CONF_PAIRING_CODE: error}


def _text_property(properties: dict[str, Any], key: str) -> str:
    """Read one mDNS TXT record as text.

    Home Assistant usually decodes these, but not always: an undecodable
    record arrives as bytes, and str() on that would yield "b't560'".
    """
    value = properties.get(key)
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    return str(value or "").strip()


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

    # The pairing being negotiated, and its result.
    _pair_task: asyncio.Task[str | None] | None = None
    _pair_error: str | None = None
    _refresh_token_id: str = ""
    _user_id: str = ""

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
        _LOGGER.debug(
            "Panel announcement from %s: %s", discovery_info.host, properties
        )
        panel_id = _text_property(properties, ZEROCONF_PROP_PANEL_ID)
        if not panel_id:
            return self.async_abort(reason="no_panel_id")

        await self.async_set_unique_id(panel_unique_id(panel_id))
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: discovery_info.host}
        )

        self._panel_id = panel_id
        self._profile = panel_profile(
            _text_property(properties, ZEROCONF_PROP_PROFILE)
        )
        self._panel_name = (
            _text_property(properties, ZEROCONF_PROP_NAME) or panel_id
        )
        self._panel_host = discovery_info.host

        # Shown on the discovery card in the UI.
        self.context["title_placeholders"] = {
            "name": self._panel_name,
            "profile": self._profile.name,
        }
        return await self.async_step_pair()

    async def async_step_panel(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Add a panel by hand, for a device that cannot announce itself.

        A controller is not required to get this far: if none exists, the flow
        offers to build one after pairing, in async_step_new_controller.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            self._profile = panel_profile(user_input[CONF_PROFILE])
            self._panel_id = user_input[CONF_PANEL_ID].strip().lower()
            self._panel_name = (
                str(user_input.get(CONF_NAME) or "").strip() or self._panel_id
            )
            await self.async_set_unique_id(panel_unique_id(self._panel_id))
            self._abort_if_unique_id_configured()
            return await self.async_step_pair()

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
                }
            ),
            errors=errors,
        )

    # ------------------------------------------------------------------- pairing

    async def async_step_pair(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Ask for the code the panel is showing, before anything else.

        The panel shows it; nothing is typed on the panel, and the token never
        travels over SSH.

        Pairing needs no controller. Whether one exists is settled afterwards,
        in async_step_controller_link, which offers to create one rather than
        sending anybody off to another flow: adding a panel is one sitting —
        the code, then what it plays from, then its room controls.

        Nothing here may abort, either. This step is what `async_step_zeroconf`
        returns, so an abort becomes the *result of the discovery* and Home
        Assistant never offers the device at all. A panel that is announcing
        itself correctly must always produce a card.
        """
        if user_input is not None:
            self._pair_error = self._arm_pairing(
                str(user_input[CONF_PAIRING_CODE]).strip()
            )
            if self._pair_error is None:
                return await self.async_step_pair_wait()

        return self.async_show_form(
            step_id="pair",
            data_schema=_pairing_schema(),
            errors=_pairing_errors(self._pair_error),
            description_placeholders={
                "name": self._panel_name,
                "profile": self._profile.name,
                "host": self._panel_host or "unknown",
            },
        )

    async def async_step_pair_wait(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Wait for the panel to answer with the same code.

        Shared by both paths: a panel being added and a panel being paired
        again. Where it goes next is decided in async_step_pair_result.
        """
        if self._pair_task is None:
            self._pair_task = self.hass.async_create_task(
                self._async_wait_for_panel(),
                f"media_controller pairing {self._panel_id}",
            )
        if not self._pair_task.done():
            return self.async_show_progress(
                step_id="pair_wait",
                progress_action="waiting_for_panel",
                progress_task=self._pair_task,
                description_placeholders={"name": self._panel_name},
            )
        return self.async_show_progress_done(next_step_id="pair_result")

    async def async_step_pair_result(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Continue once the panel has answered, or ask for the code again."""
        task, self._pair_task = self._pair_task, None
        try:
            error = "pairing_timeout" if task is None else task.result()
        except Exception:  # noqa: BLE001 - surfaced as a form error
            _LOGGER.exception("Waiting for the panel failed")
            error = "pairing_timeout"

        if error is None:
            if self.source == config_entries.SOURCE_REAUTH:
                return await self._async_finish_reauth()
            return await self.async_step_controller_link()

        _pairings(self.hass).discard(self._panel_id)
        self._pair_error = error
        if self.source == config_entries.SOURCE_REAUTH:
            return await self.async_step_reauth_confirm()
        return await self.async_step_pair()

    @callback
    def _arm_pairing(self, code: str) -> str | None:
        """Open the pairing window for the code that was typed.

        No token is minted here. One is created when the entry that owns it is
        about to exist, so a setup that is closed halfway through leaves
        nothing usable in Home Assistant.
        """
        if not is_valid_code(code):
            return "invalid_code"
        _pairings(self.hass).arm(self._panel_id, code)
        return None

    async def _async_wait_for_panel(self) -> str | None:
        """Return None once the panel has shown it holds the same code.

        All that is settled here is whether the right device is listening.
        """
        pairings = _pairings(self.hass)
        deadline = time.monotonic() + PAIRING_TIMEOUT
        while True:
            state = pairings.state(self._panel_id)
            if state in (STATE_CONFIRMED, STATE_COLLECTED):
                return None
            if state == STATE_REJECTED:
                return "code_mismatch"
            if state is None or time.monotonic() >= deadline:
                return "pairing_timeout"
            await asyncio.sleep(PAIRING_POLL_INTERVAL)

    async def _async_mint_token(self, name: str) -> str | None:
        """Create the panel's token and let the endpoint hand it over.

        Returns an error key, or None once the token is on its way. It is
        attached to the pairing rather than sent anywhere: the panel collects
        it on its next poll, once its config sensor also exists.
        """
        try:
            token, refresh_token_id, user_id = await async_create_panel_token(
                self.hass, name
            )
        except Exception:  # noqa: BLE001 - surfaced as a form error
            _LOGGER.exception("Could not create a token for the panel")
            return "token_failed"

        self._refresh_token_id = refresh_token_id
        self._user_id = user_id
        if not _pairings(self.hass).attach_token(self._panel_id, token):
            # The approval expired between the last form and this moment. The
            # entry is still written, and the panel asks for the token again
            # through the reauthentication prompt.
            _LOGGER.warning(
                "The pairing of panel %s expired before its token could be "
                "handed over; it will ask again",
                self._panel_id,
            )
        return None

    # ------------------------------------------------------------- panel setup

    async def async_step_controller_link(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Attach the paired panel to a controller.

        With no controller yet there is nothing to choose between, so the flow
        asks for the player instead and builds one. A panel is added in one
        sitting either way.
        """
        controllers = controller_entries(self.hass)
        if not controllers:
            return await self.async_step_new_controller()

        if user_input is not None:
            self._controller_entry_id = user_input[CONF_CONTROLLER_ENTRY_ID]
            return await self.async_step_slots()

        default = controllers[0].entry_id
        return self.async_show_form(
            step_id="controller_link",
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

    async def async_step_new_controller(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Build the controller this panel will play from, in this flow.

        The first panel in an installation has nothing to attach to, and
        telling somebody to go and add one somewhere else is not an answer:
        they came here to add a device. So this asks the one question a
        controller actually needs — which Music Assistant player — and creates
        it before carrying on to the room controls.

        Only the player is asked for. A controller also carries four room slots
        of its own, but those belong to an ESP32 on the classic firmware; a
        controller created from here has none, and they can be filled later
        from its own Configure.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            player_entity = user_input[CONF_PLAYER_ENTITY]
            if _music_assistant_registry_entry(self.hass, player_entity) is None:
                errors[CONF_PLAYER_ENTITY] = "not_music_assistant"
            else:
                entry_id = await self._async_create_controller(player_entity)
                if entry_id is None:
                    errors["base"] = "controller_failed"
                else:
                    self._controller_entry_id = entry_id
                    return await self.async_step_slots()

        return self.async_show_form(
            step_id="new_controller",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(
                            CONF_PLAYER_ENTITY
                        ): selector.EntitySelector(
                            selector.EntitySelectorConfig(
                                domain="media_player",
                                integration=MUSIC_ASSISTANT_DOMAIN,
                            )
                        ),
                    }
                ),
                user_input or {},
            ),
            errors=errors,
            description_placeholders={"name": self._panel_name},
        )

    async def _async_create_controller(self, player_entity: str) -> str | None:
        """Create a controller entry and return its ID.

        A config flow creates one entry, and this flow's entry is the panel, so
        the controller is made by starting the import flow below and taking the
        entry it produced.
        """
        result = await self.hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_IMPORT},
            data={CONF_PLAYER_ENTITY: player_entity},
        )
        entry = result.get("result")
        if result.get("type") is not FlowResultType.CREATE_ENTRY or entry is None:
            _LOGGER.error(
                "Could not create a controller for %s: %s",
                player_entity,
                result.get("reason") or result.get("type"),
            )
            return None
        return entry.entry_id

    async def async_step_import(
        self,
        import_data: dict[str, Any],
    ) -> ConfigFlowResult:
        """Create a controller without asking anything.

        Used only by _async_create_controller, so that adding the first panel
        does not have to send anybody to a second flow.
        """
        player_entity = import_data[CONF_PLAYER_ENTITY]
        registry_entry = _music_assistant_registry_entry(
            self.hass, player_entity
        )
        if registry_entry is None:
            return self.async_abort(reason="not_music_assistant")

        await self.async_set_unique_id(_controller_unique_id(registry_entry))
        self._abort_if_unique_id_configured()
        state = self.hass.states.get(player_entity)
        title = state.name if state is not None else player_entity
        return self.async_create_entry(
            title=f"Media Controller – {title}",
            data=_stored_controller(player_entity, []),
        )

    async def async_step_slots(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Fill the room-control slots, and finish the panel.

        Submitting this form is what releases the token: it is minted here and
        the endpoint hands it over once the config sensor the panel has to
        read exists too.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            state = _pairings(self.hass).state(self._panel_id)
            if state != STATE_CONFIRMED:
                # The tablet stopped answering while the form was open, so
                # the code has to be read off it again.
                self._pair_error = (
                    "code_mismatch"
                    if state == STATE_REJECTED
                    else "pairing_timeout"
                )
                return await self.async_step_pair()

            slots = [
                slot.as_stored()
                for slot in slots_from_input(
                    self.hass, self._profile, user_input
                )
            ]
            error = await self._async_mint_token(
                self._panel_name or self._panel_id
            )
            if error is None:
                return self.async_create_entry(
                    title=self._panel_name or self._profile.name,
                    data={
                        CONF_ENTRY_TYPE: ENTRY_TYPE_PANEL,
                        CONF_PROFILE: self._profile.slug,
                        CONF_PANEL_ID: self._panel_id,
                        CONF_NAME: self._panel_name,
                        CONF_HOST: self._panel_host,
                        CONF_CONTROLLER_ENTRY_ID: self._controller_entry_id,
                        CONF_REFRESH_TOKEN_ID: self._refresh_token_id,
                        CONF_USER_ID: self._user_id,
                        CONF_SLOTS: slots,
                    },
                )
            errors = _pairing_errors(error)

        return self.async_show_form(
            step_id="slots",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_slot_fields(self._profile)), user_input or {}
            ),
            errors=errors,
            description_placeholders={
                "name": self._panel_name,
                "profile": self._profile.name,
                "slot_count": str(self._profile.slot_count),
            },
        )

    # ---------------------------------------------------------------- re-pairing

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],
    ) -> ConfigFlowResult:
        """A configured panel lost its token and is asking for a new one."""
        entry = self._get_reauth_entry()
        self._panel_id = entry.data.get(CONF_PANEL_ID, "")
        self._panel_name = entry.title or self._panel_id
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
        if user_input is not None:
            self._pair_error = self._arm_pairing(
                str(user_input[CONF_PAIRING_CODE]).strip()
            )
            if self._pair_error is None:
                return await self.async_step_pair_wait()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_pairing_schema(),
            errors=_pairing_errors(self._pair_error),
            description_placeholders={"name": self._panel_name},
        )

    async def _async_finish_reauth(self) -> ConfigFlowResult:
        """Mint and store the new token of a panel that has answered."""
        entry = self._get_reauth_entry()
        error = await self._async_mint_token(self._panel_name)
        if error is not None:
            self._pair_error = error
            return await self.async_step_reauth_confirm()

        # The old token is revoked only once the new one is on its way to the
        # panel, so a failed attempt cannot leave it with neither.
        await async_revoke_panel_token(
            self.hass,
            entry.data.get(CONF_USER_ID),
            entry.data.get(CONF_REFRESH_TOKEN_ID),
        )
        return self.async_update_reload_and_abort(
            entry,
            data_updates={
                CONF_REFRESH_TOKEN_ID: self._refresh_token_id,
                CONF_USER_ID: self._user_id,
            },
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
    """Edit what one panel plays from and the room controls it draws.

    The device type is not offered again: it decides how many proxies exist,
    so changing it is a delete-and-add operation. The controller is offered,
    because moving a panel to another player is a remapping like any other and
    used to require deleting the panel and pairing the tablet again.
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
        """Remap the panel's controller and slots, and reload automatically."""
        entry = self.config_entry
        profile = panel_profile(entry.data.get(CONF_PROFILE))
        current = (
            stored_slots(entry.options, CONF_SLOTS)
            if CONF_SLOTS in entry.options
            else stored_slots(entry.data, CONF_SLOTS)
        )
        controller_entry_id = entry.options.get(
            CONF_CONTROLLER_ENTRY_ID,
            entry.data.get(CONF_CONTROLLER_ENTRY_ID, ""),
        )

        if user_input is not None:
            slots = slots_from_input(self.hass, profile, user_input, current)
            return self.async_create_entry(
                data={
                    CONF_CONTROLLER_ENTRY_ID: user_input[
                        CONF_CONTROLLER_ENTRY_ID
                    ],
                    CONF_SLOTS: [slot.as_stored() for slot in slots],
                }
            )

        suggested: dict[str, Any] = {
            CONF_CONTROLLER_ENTRY_ID: controller_entry_id
        }
        suggested.update(suggested_slot_values(current))
        return self.async_show_form(
            step_id="slots",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(
                            CONF_CONTROLLER_ENTRY_ID
                        ): _controller_selector(self.hass),
                        **_slot_fields(profile),
                    }
                ),
                suggested,
            ),
            description_placeholders={
                "name": entry.title,
                "profile": profile.name,
                "slot_count": str(profile.slot_count),
            },
        )
