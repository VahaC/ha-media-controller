"""Config and options flows for Media Controller.

Two kinds of entry live in this domain, and the flows exist to keep the
difference obvious. A **media player source** is bound to a Music Assistant
player and owns the queue and playlist sensors; it is registered as a service,
so Home Assistant lists it apart from the hardware. A **panel** is a client
device — a tablet, or an ESP32 on the paired firmware — that reads one source
and is a device like any other. It is normally created by discovery, when the
panel announces itself on the local network.

A panel cannot exist without a source, and the ordering is built into the
flows rather than explained in prose: the menu is skipped while there is no
source, and a panel that pairs with none offers to make one on the spot.

In code the source is still called a controller. Renaming it across the entry
data, the shared runtime records and the panel's stored `controller_entry_id`
would be a migration that buys nothing; the user-facing strings carry the
name, and they are the ones that were confusing.

No form asks for a panel ID. A panel that announces itself over mDNS carries
one in its record, and a panel that cannot announce itself sends one every
three seconds anyway, in the poll it has to make before it can hold a token —
provision.py turns that poll into a discovered device. Both roads arrive at
the same place with the identifier already known, which is the only honest
arrangement: an ESP32 panel never shows its MAC on screen, so anybody typing
one would have been guessing.

A panel is paired first and configured afterwards. The tablet is the one part
of the setup that can fail on its own — it may be off, on another network, or
showing a code from an older attempt — so the flow settles that before asking
anyone to map room controls. Nothing is stored until the panel has answered
with the code it is showing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
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

from .bootstrap import normalise_url
from .const import (
    CONF_CONTROLLER_ENTRY_ID,
    CONF_ENTITIES,
    CONF_PAIRING_CODE,
    CONF_REFRESH_TOKEN_ID,
    CONF_RETIRED_RIDS,
    CONF_USER_ID,
    DATA_PROVISIONING,
    CONF_ENTRY_TYPE,
    CONF_HA_URL,
    CONF_HOST,
    CONF_NAME,
    CONF_PANEL_ID,
    CONF_PANEL_PORT,
    CONF_PLAYER_ENTITY,
    CONF_PROFILE,
    CONF_SLOTS,
    DOMAIN,
    ENTRY_TYPE_CONTROLLER,
    ENTRY_TYPE_PANEL,
    ENTRY_VERSION,
    INSTALLER_URL,
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
from .panel_provision import (
    async_internal_url,
    async_panel_accepts_push,
    async_verify_code,
)
from .profiles import (
    CONTROLLER_PROFILE,
    PANEL_PROFILES,
    ClientProfile,
    panel_profile,
    profile_from_panel_id,
)
from .registry import (
    GROUPS,
    RETIRED_GROUP_DOMAINS,
    RegistryEntry,
    RegistryGroup,
    group_by_slug,
    group_selection,
    replace_group,
    stored_retired_rids,
)
from .slots import (
    SlotConfig,
    seed_registry_ids,
    slots_from_input,
    stored_entries,
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


def _ha_url_schema(suggested: str) -> vol.Schema:
    """Ask where Home Assistant is, for a panel that has to be told."""
    return vol.Schema(
        {
            vol.Required(CONF_HA_URL, default=suggested): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
            ),
        }
    )


def _profile_selector() -> selector.SelectSelector:
    """List the kinds of panel there are, by what each one can draw."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(
                    value=profile.slug,
                    label=(
                        f"{profile.name} "
                        f"(up to {profile.entity_limit} room entities)"
                    ),
                )
                for profile in PANEL_PROFILES
            ],
            mode=selector.SelectSelectorMode.LIST,
        )
    )


def _unnamed_panel(panel_id: str) -> str:
    """Name a panel that has not said what it is called.

    Only a panel that arrived by polling gets here; one that announced itself
    carried a name. Four characters are enough to tell two of them apart and
    short enough to read, and they are the end of a MAC address, which is
    what is printed on the back of most boards.

    The kind of panel is deliberately not part of this. It is a guess until
    the pairing form comes back, and a suggested name that changed under
    somebody correcting that guess would be worse than a plain one.
    """
    return f"Panel {panel_id[-4:]}".strip()


def _pairing_schema(profile: ClientProfile | None = None) -> vol.Schema:
    """Ask for the code the panel is showing on its own screen.

    A panel discovered over mDNS said what it is and what it is called. A
    panel that only polled for a token said neither, so those two questions
    are asked here, on the form that was going to be shown anyway, rather
    than on a page of their own before it.
    """
    fields: dict[Any, Any] = {
        vol.Required(CONF_PAIRING_CODE): selector.TextSelector(),
    }
    if profile is not None:
        fields[vol.Required(CONF_PROFILE, default=profile.slug)] = (
            _profile_selector()
        )
        fields[vol.Optional(CONF_NAME)] = selector.TextSelector()
    return vol.Schema(fields)


# Failures that are not about the six digits, so putting them on that field
# would be telling somebody to retype a code that was fine.
_PAIRING_BASE_ERRORS = frozenset({"token_failed", "panel_refused"})


def _pairing_errors(error: str | None) -> dict[str, str]:
    """Place a pairing failure on the field the person can act on."""
    if error is None:
        return {}
    if error in _PAIRING_BASE_ERRORS:
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


# The order the registry form lists its groups in. Payload order lives in
# registry.GROUPS, because that is the client's; this is the reading order of
# one page of settings, and a group this list forgets is simply shown last.
FORM_GROUP_ORDER: tuple[str, ...] = (
    "weather",
    "sensors",
    "lights",
    "switches",
    "climate",
    "covers",
)


def _form_groups() -> tuple[RegistryGroup, ...]:
    """Return every group, in the order the form reads best in."""
    listed = [
        group
        for slug in FORM_GROUP_ORDER
        if (group := group_by_slug(slug)) is not None
    ]
    named = {group.slug for group in listed}
    return tuple(listed) + tuple(
        group for group in GROUPS if group.slug not in named
    )


class RegistryFlowMixin:
    """Editing a panel's entity registry, shared by both of its flows.

    The whole registry is **one form**. Every group is a multi-entity picker
    of its own domain, so adding a light and a thermostat is one visit and one
    Submit; nothing here opens a dialog on top of a dialog.

    `rid` is the identity of an element rather than of the entity behind it,
    so deselecting an entity **deletes** its element and retires its rid; that
    is why `_retired` travels with the registry and is stored beside it. A
    tile is labelled by the entity's own Home Assistant name, and nothing here
    asks for a second one.

    A flow with more to ask than the registry adds its own fields through
    `_registry_extra_fields`, rather than putting them behind a menu.
    """

    hass: Any
    _profile: ClientProfile
    _registry: list[RegistryEntry]
    _retired: list[str]

    async def _async_registry_done(
        self,
        user_input: Mapping[str, Any],
    ) -> ConfigFlowResult:
        """Store the edited registry; the owning flow decides where."""
        raise NotImplementedError

    # -------------------------------------------------------------- the form

    async def async_step_entities(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Show every group at once, and apply what comes back."""
        if user_input is None:
            return self._async_registry_form()
        if (error := self._async_apply_registry(user_input)) is not None:
            return self._async_registry_form(user_input, {"base": error})
        return await self._async_registry_done(user_input)

    @callback
    def _async_registry_form(
        self,
        user_input: Mapping[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        """Render the one page: the flow's own fields, then every group."""
        fields: dict[Any, Any] = dict(self._registry_extra_fields())
        for group in _form_groups():
            fields[vol.Optional(group.slug)] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=group.domain, multiple=True
                )
            )

        suggested: dict[str, Any] = {
            **self._registry_extra_suggested(),
            **{
                group.slug: group_selection(self._registry, group.domain)
                for group in _form_groups()
            },
        }
        return self.async_show_form(
            step_id=self._registry_step_id(),
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(fields), dict(user_input or suggested)
            ),
            errors=errors or {},
            description_placeholders=self._registry_placeholders(),
        )

    @callback
    def _async_apply_registry(
        self,
        user_input: Mapping[str, Any],
    ) -> str | None:
        """Rewrite every group from one submission.

        A group the form did not send back is an emptied one: Home Assistant
        drops an optional field that has no value, and clearing the picker is
        the only way to empty a group. Nothing is kept until every group has
        been rewritten, so the limit is checked against the whole registry.
        """
        registry = [
            entry
            for entry in self._registry
            if entry.domain not in RETIRED_GROUP_DOMAINS
        ]
        retired = list(self._retired) + [
            entry.rid
            for entry in self._registry
            if entry.domain in RETIRED_GROUP_DOMAINS
        ]
        for group in GROUPS:
            registry, newly_retired = replace_group(
                registry,
                group.domain,
                user_input.get(group.slug) or (),
                retired=retired,
            )
            retired.extend(newly_retired)

        if len(registry) > self._profile.entity_limit:
            return "too_many_entities"

        self._registry = registry
        self._retired = retired
        return None

    # ------------------------------------------------- what a flow may change

    @callback
    def _registry_step_id(self) -> str:
        """Return the step ID the form is rendered and translated under."""
        return "entities"

    @callback
    def _registry_extra_fields(self) -> dict[Any, Any]:
        """Return the fields the owning flow puts above the groups."""
        return {}

    @callback
    def _registry_extra_suggested(self) -> dict[str, Any]:
        """Return the current values of those fields."""
        return {}

    @callback
    def _registry_extra_placeholders(self) -> dict[str, str]:
        """Return anything the owning flow's description needs."""
        return {}

    @callback
    def _registry_placeholders(self) -> dict[str, str]:
        """Describe the registry to the step's description."""
        return {
            "profile": self._profile.name,
            "entity_limit": str(self._profile.entity_limit),
            "remaining": str(
                max(self._profile.entity_limit - len(self._registry), 0)
            ),
            **self._registry_extra_placeholders(),
        }

    @callback
    def _stored_registry(self) -> list[dict[str, Any]]:
        """Return the registry in its on-disk shape, ready to store.

        The entity-registry row of every target is recorded here rather than
        at load: a rename that happens in between is followed by that row, and
        at load there would be nothing left to look it up by.
        """
        return [
            entry.as_stored()
            for entry in seed_registry_ids(self.hass, self._registry)
        ]


def _player_schema() -> vol.Schema:
    """Ask for the Music Assistant player a source is bound to.

    This is everything a source is. The four room controls that also live on
    a source entry belong to an ESP32 running the classic firmware, and asking
    for them here made a source read like a device with buttons; they are in
    its options instead, behind a step that says whom they are for.
    """
    return vol.Schema(
        {
            vol.Required(CONF_PLAYER_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="media_player",
                    integration=MUSIC_ASSISTANT_DOMAIN,
                )
            ),
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


def _controller_title(hass: Any, player_entity: str) -> str:
    """Name a source after the player it is bound to.

    Nothing is prefixed. The integration page already says which integration
    this belongs to, and a source is registered as a service, so it is listed
    apart from the panels without the title having to spell the difference out.
    """
    state = hass.states.get(player_entity)
    return state.name if state is not None else player_entity


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
    RegistryFlowMixin,
    config_entries.ConfigFlow,
    domain=DOMAIN,
):
    """Handle controller setup and panel discovery."""

    VERSION = ENTRY_VERSION

    _profile: ClientProfile = PANEL_PROFILES[0]
    _panel_id: str = ""
    _panel_name: str = ""
    _panel_host: str = ""
    # Non-zero when the panel serves a provisioning endpoint, which is what
    # decides the direction of pairing: Home Assistant pushes to a panel that
    # can be reached and waits to be polled by one that cannot.
    _panel_port: int = 0
    # Set once the panel itself has confirmed the code over that endpoint.
    _panel_confirmed: bool = False
    # False for a panel that arrived by polling rather than by announcing
    # itself: its record said nothing about what kind of device it is, so the
    # pairing form carries that question too.
    _profile_known: bool = True
    # Only when Home Assistant could not work out its own address.
    _ha_url: str = ""
    _controller_entry_id: str = ""

    # A panel is created with an empty registry and fills it in the editor.
    _registry: list[RegistryEntry] = []
    _retired: list[str] = []

    # The pairing being negotiated, and its result.
    _pair_task: asyncio.Task[str | None] | None = None
    _pair_error: str | None = None
    _refresh_token_id: str = ""
    _user_id: str = ""

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Ask what is being added, when there is anything to ask.

        A panel plays from a source and cannot be attached to one that does
        not exist, so on a first installation the menu would be offering a
        choice with one real answer. It is skipped: the source is asked for
        directly, and the panel is added afterwards — normally by announcing
        itself, without anybody opening this flow at all.

        There is no entry here for adding a panel. Every panel arrives as a
        discovered device — by announcing itself over mDNS, or by polling for
        a token, which provision.py offers the same way — and a form that
        added one by hand could only do it by asking somebody to type an
        identifier no panel displays. What belongs here instead is the step
        before that: where a panel that does not exist yet comes from.
        """
        if not controller_entries(self.hass):
            return await self.async_step_controller()
        return self.async_show_menu(
            step_id="user",
            menu_options=["controller", "install_firmware"],
        )

    async def async_step_install_firmware(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Say where a panel that does not exist yet comes from.

        A device has to be installed before it can be discovered, and this is
        where somebody goes looking for it: "Add device" is the first thing
        opened by a person holding a new board. Nothing is configured here and
        nothing is stored — the step exists to carry one address, and Submit
        goes back to the menu.

        It is a form rather than an abort because an abort would read as a
        failure, and rather than a link buried in another step's description
        because that is not where anybody looks for it.
        """
        if user_input is not None:
            return await self.async_step_user()

        return self.async_show_form(
            step_id="install_firmware",
            data_schema=vol.Schema({}),
            description_placeholders={"installer_url": INSTALLER_URL},
            last_step=False,
        )

    # ---------------------------------------------------------------- controller

    async def async_step_controller(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Bind a source to a Music Assistant player.

        A source is created with no room controls. The four that a source can
        carry are the classic ESP32 firmware's, and it is the only client that
        reads them; they are filled in from the source's own options.
        """
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
                return self.async_create_entry(
                    title=_controller_title(self.hass, player_entity),
                    data=_stored_controller(player_entity, []),
                )

        return self.async_show_form(
            step_id="controller",
            data_schema=self.add_suggested_values_to_schema(
                _player_schema(), user_input or {}
            ),
            errors=errors,
        )

    # ----------------------------------------------------------- discovery

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
        # The port is refreshed alongside the address, and it has to be: a
        # probe that failed while somebody was typing a code stores a zero,
        # and a zero means "this panel serves nothing" for the rest of its
        # life. Nothing else ever put it back, so one unlucky moment demoted a
        # panel Home Assistant pushes to into one it waits to be polled by.
        #
        # A panel announces itself continuously, so healing it here means the
        # entry repairs itself the next time the device says where it is.
        self._abort_if_unique_id_configured(
            updates={
                CONF_HOST: discovery_info.host,
                CONF_PANEL_PORT: int(discovery_info.port or 0),
            }
        )

        self._panel_id = panel_id
        self._profile = panel_profile(
            _text_property(properties, ZEROCONF_PROP_PROFILE)
        )
        self._registry = []
        self._retired = []
        self._panel_name = (
            _text_property(properties, ZEROCONF_PROP_NAME) or panel_id
        )
        self._panel_host = discovery_info.host
        # A tablet advertises port 0 because it serves nothing; the ESP32
        # firmware advertises the port its provisioning endpoint is on. The
        # record therefore says which way round pairing runs, with no second
        # service type and no new TXT key.
        self._panel_port = int(discovery_info.port or 0)

        # Shown on the discovery card in the UI.
        self.context["title_placeholders"] = {
            "name": self._panel_name,
            "profile": self._profile.name,
        }
        return await self.async_step_pair()

    async def async_step_integration_discovery(
        self,
        discovery_info: dict[str, Any],
    ) -> ConfigFlowResult:
        """Offer a panel that asked for a token instead of announcing itself.

        A panel with no token polls the provisioning endpoint every three
        seconds and is answered `unknown_panel` until somebody adds it. That
        poll is a discovery: it proves the panel exists, it proves it can
        reach Home Assistant, and it carries the panel's identifier. So
        provision.py starts this flow with it, and a panel that mDNS never
        reached still turns up as a device to click on.

        Two things the mDNS record would have said are missing: what kind of
        panel it is, and what it is called. Both are asked on the pairing
        form rather than here, so that this path is still one form long.

        Nothing may abort except a panel that is already configured: an abort
        is the result of the discovery, and it would take the card with it.
        """
        panel_id = str(discovery_info.get(CONF_PANEL_ID) or "").strip().lower()
        if not panel_id:
            return self.async_abort(reason="no_panel_id")

        # Also what stops a second card while one is already up: a flow in
        # progress for this panel ends the new one here.
        await self.async_set_unique_id(panel_unique_id(panel_id))
        self._abort_if_unique_id_configured()

        self._panel_id = panel_id
        self._registry = []
        self._retired = []
        # A guess, and only the default of a question that is still asked.
        self._profile = profile_from_panel_id(panel_id)
        self._profile_known = False
        self._panel_name = ""
        # It polled, so it is the polling kind: nothing is known about where
        # it is, and nothing may be pushed to it.
        self._panel_host = ""
        self._panel_port = 0

        # Shown on the discovery card, before anybody has named it.
        self.context["title_placeholders"] = {
            "name": _unnamed_panel(panel_id),
            "profile": self._profile.name,
        }
        return await self.async_step_pair()

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

        Nothing here may abort, either. This step is what both discovery
        steps return, so an abort becomes the *result of the discovery* and
        Home Assistant never offers the device at all. A panel that reached
        Home Assistant at all must always produce a card.

        It also carries the two questions the mDNS record answers and a poll
        does not — what kind of panel this is, and what to call it — for the
        panel that arrived the second way. They are asked here rather than
        before the code because a panel that never answers makes both
        pointless, and because one form is better than two.
        """
        if user_input is not None:
            if not self._profile_known:
                # Asked here rather than before the code, because a panel that
                # never answers makes both answers pointless.
                self._profile = panel_profile(user_input[CONF_PROFILE])
                self._panel_name = str(
                    user_input.get(CONF_NAME) or ""
                ).strip()
            code = str(user_input[CONF_PAIRING_CODE]).strip()
            self._pair_error = await self._async_offer_code(code)
            if self._pair_error is None:
                if not self._panel_name:
                    self._panel_name = _unnamed_panel(self._panel_id)
                if self._panel_confirmed:
                    # The panel answered directly, so there is nothing to wait
                    # for. Its token is minted at the end of the form and
                    # delivered once the entities it names exist.
                    return await self.async_step_controller_link()
                return await self.async_step_pair_wait()

        shown = self._panel_name or _unnamed_panel(self._panel_id)
        return self.async_show_form(
            step_id="pair",
            data_schema=self.add_suggested_values_to_schema(
                _pairing_schema(
                    None if self._profile_known else self._profile
                ),
                {CONF_NAME: shown} if not self._profile_known else {},
            ),
            errors=_pairing_errors(self._pair_error),
            description_placeholders={
                "name": shown,
                "profile": self._profile.name,
                "host": self._panel_host or "unknown",
            },
        )

    async def async_step_ha_url(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Ask where Home Assistant is, when it cannot say itself.

        Only reached for a panel Home Assistant has to push to — a panel that
        polls already knows the address — and only when the network helpers
        have nothing to offer. That is rare enough that asking every time
        would be a step nobody needs, and possible enough that not asking
        would strand the setup with no way forward.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            # Checked against the same rule the panel applies, so a value it
            # would refuse is caught while somebody is still looking at a form
            # rather than three steps later in a log line.
            candidate = normalise_url(user_input.get(CONF_HA_URL))
            if not candidate:
                errors[CONF_HA_URL] = "invalid_url"
            else:
                self._ha_url = candidate
                if self.source == config_entries.SOURCE_REAUTH:
                    return await self._async_finish_reauth()
                return await self._async_registry_done({})

        return self.async_show_form(
            step_id="ha_url",
            data_schema=_ha_url_schema(self._ha_url),
            errors=errors,
            description_placeholders={"name": self._panel_name},
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

    async def _async_offer_code(self, code: str) -> str | None:
        """Settle the code, whichever way round this panel pairs.

        A panel that serves a provisioning endpoint is asked outright, and
        answers in one request: no token has been minted at this point, so a
        wrong code costs nothing and leaves nothing behind. A panel that
        serves nothing has the code held for it instead, and confirms it on
        its next poll.

        A panel that was discovered on a port but does not answer on it falls
        back to the poll: an ESP32 still booting, or a device whose web server
        is busy, must not be told its code was wrong.
        """
        self._panel_confirmed = False
        if not is_valid_code(code):
            return "invalid_code"

        if self._panel_port and await self._async_panel_answers():
            error = await async_verify_code(
                self.hass, self._panel_host, self._panel_port, code
            )
            if error is not None:
                return error
            self._panel_confirmed = True
            # The record still has to exist: it is what carries the token from
            # the moment it is minted to the moment it is delivered.
            _pairings(self.hass).confirmed(self._panel_id, code)
            return None

        _pairings(self.hass).arm(self._panel_id, code)
        return None

    async def _async_panel_answers(self) -> bool:
        """Return whether the discovered address really is this panel.

        A no is remembered rather than only returned: the port is what the
        entry stores to decide the direction of every later delivery, and a
        device that turned out not to be there must not be pushed to after
        it was paired the long way round.
        """
        if await async_panel_accepts_push(
            self.hass, self._panel_host, self._panel_port, self._panel_id
        ):
            return True
        self._panel_port = 0
        return False

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
            return await self.async_step_entities()

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
                "entity_limit": str(self._profile.entity_limit),
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
                    return await self.async_step_entities()

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
        return self.async_create_entry(
            title=_controller_title(self.hass, player_entity),
            data=_stored_controller(player_entity, []),
        )

    async def _async_registry_done(
        self,
        user_input: Mapping[str, Any],
    ) -> ConfigFlowResult:
        """Finish the panel once its room entities have been chosen.

        Leaving the registry editor is what releases the token: it is minted
        here and the endpoint hands it over once the config sensor the panel
        has to read exists too.
        """
        state = _pairings(self.hass).state(self._panel_id)
        if state != STATE_CONFIRMED:
            # The tablet stopped answering while the form was open, so the
            # code has to be read off it again.
            self._pair_error = (
                "code_mismatch"
                if state == STATE_REJECTED
                else "pairing_timeout"
            )
            return await self.async_step_pair()

        # A panel that has to be told where Home Assistant is cannot be
        # finished until somebody has said. Asked last, so the one setup in a
        # hundred that needs it does not slow down the other ninety-nine.
        if (
            self._panel_confirmed
            and not self._ha_url
            and async_internal_url(self.hass) is None
        ):
            return await self.async_step_ha_url()

        entities = self._stored_registry()
        error = await self._async_mint_token(
            self._panel_name or self._panel_id
        )
        if error is not None:
            self._pair_error = error
            return await self.async_step_pair()

        return self.async_create_entry(
            title=self._panel_name or self._profile.name,
            data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_PANEL,
                CONF_PROFILE: self._profile.slug,
                CONF_PANEL_ID: self._panel_id,
                CONF_NAME: self._panel_name,
                CONF_HOST: self._panel_host,
                CONF_PANEL_PORT: self._panel_port,
                CONF_HA_URL: self._ha_url,
                CONF_CONTROLLER_ENTRY_ID: self._controller_entry_id,
                CONF_REFRESH_TOKEN_ID: self._refresh_token_id,
                CONF_USER_ID: self._user_id,
                CONF_ENTITIES: entities,
                CONF_RETIRED_RIDS: list(self._retired),
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
        self._panel_host = entry.data.get(CONF_HOST, "")
        self._panel_port = int(entry.data.get(CONF_PANEL_PORT) or 0)
        self._ha_url = entry.data.get(CONF_HA_URL, "")
        # Read from the entry rather than left at the class default, which is
        # the first panel profile and would be the wrong device here.
        self._profile = panel_profile(entry.data.get(CONF_PROFILE))
        # Every flow that appears as its own card has to fill these in.
        # `flow_title` is "{name} ({profile})" and is rendered for this flow
        # exactly as it is for a discovery, so leaving them out does not
        # produce a plain title — it produces a formatjs MISSING_VALUE error
        # in place of the row, which is the one row telling somebody their
        # panel has lost its token.
        self.context["title_placeholders"] = {
            "name": self._panel_name,
            "profile": self._profile.name,
        }
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
            self._pair_error = await self._async_offer_code(
                str(user_input[CONF_PAIRING_CODE]).strip()
            )
            if self._pair_error is None:
                if self._panel_confirmed:
                    return await self._async_finish_reauth()
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
        # Same question as when the panel was added, and it can be a different
        # answer now: Home Assistant may have been given an internal URL since,
        # or lost the one it had.
        if (
            self._panel_confirmed
            and not self._ha_url
            and async_internal_url(self.hass) is None
        ):
            return await self.async_step_ha_url()

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
        # Reloading is what delivers the new token to a panel that is pushed
        # to: async_setup_entry finds the pairing waiting with a token
        # attached and posts it once the config sensor exists again. A panel
        # that polls collects it the same way it always did.
        return self.async_update_reload_and_abort(
            entry,
            data_updates={
                CONF_REFRESH_TOKEN_ID: self._refresh_token_id,
                CONF_USER_ID: self._user_id,
                CONF_PANEL_PORT: self._panel_port,
                CONF_HA_URL: self._ha_url,
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
    """Edit what a source plays, and the classic ESP32's room controls.

    The two are asked for separately. Everybody who has a source has a player;
    almost nobody has a classic-firmware ESP32, and putting its four slots in
    the same form as the player made every source look like a device with
    buttons on it. The menu names who the second step is for.

    Options are stored whole, so each step writes both halves: the one it just
    asked about, and the one it left alone.
    """

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Offer the two things a source has."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["player", "esp32_slots"],
        )

    @callback
    def _options(
        self,
        player_entity: str,
        slots: list[SlotConfig],
    ) -> dict[str, Any]:
        """Build the whole options mapping from both halves.

        An empty player is left out rather than written: the value stored when
        the entry was created is then still what the setup reads, and a source
        cannot be left bound to nothing by editing its slots.
        """
        data: dict[str, Any] = {
            CONF_SLOTS: [slot.as_stored() for slot in slots]
        }
        if player_entity:
            data[CONF_PLAYER_ENTITY] = player_entity
        return data

    async def async_step_player(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Move a source to another Music Assistant player."""
        errors: dict[str, str] = {}
        if user_input is not None:
            player_entity = user_input[CONF_PLAYER_ENTITY]
            registry_entry = _music_assistant_registry_entry(
                self.hass, player_entity
            )
            if registry_entry is None:
                errors[CONF_PLAYER_ENTITY] = "not_music_assistant"
            elif self._player_taken(_controller_unique_id(registry_entry)):
                errors[CONF_PLAYER_ENTITY] = "already_configured"
            else:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    unique_id=_controller_unique_id(registry_entry),
                )
                return self.async_create_entry(
                    data=self._options(
                        player_entity,
                        _controller_slots(self.config_entry),
                    )
                )

        current = {
            CONF_PLAYER_ENTITY: _entry_player_entity(self.config_entry) or ""
        }
        return self.async_show_form(
            step_id="player",
            data_schema=self.add_suggested_values_to_schema(
                _player_schema(), user_input or current
            ),
            errors=errors,
        )

    @callback
    def _player_taken(self, unique_id: str) -> bool:
        """Return whether another source already holds this player."""
        for entry in controller_entries(self.hass):
            if entry.entry_id == self.config_entry.entry_id:
                continue
            if entry.unique_id == unique_id:
                return True
            other_player = _entry_player_entity(entry)
            other_registry_entry = (
                _music_assistant_registry_entry(self.hass, other_player)
                if other_player
                else None
            )
            if (
                other_registry_entry is not None
                and _controller_unique_id(other_registry_entry) == unique_id
            ):
                return True
        return False

    async def async_step_esp32_slots(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Remap the room controls of a classic-firmware ESP32."""
        current = _controller_slots(self.config_entry)
        if user_input is not None:
            slots = slots_from_input(
                self.hass, CONTROLLER_PROFILE, user_input, current
            )
            return self.async_create_entry(
                data=self._options(
                    _entry_player_entity(self.config_entry) or "",
                    slots,
                )
            )

        return self.async_show_form(
            step_id="esp32_slots",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(_slot_fields(CONTROLLER_PROFILE)),
                user_input or suggested_slot_values(current),
            ),
            description_placeholders={
                "slot_count": str(CONTROLLER_PROFILE.slot_count),
                "profile": CONTROLLER_PROFILE.name,
            },
        )


class PanelOptionsFlow(RegistryFlowMixin, OptionsFlowWithReload):
    """Edit what one panel plays from and the room entities it draws, at once.

    The device type is not offered again: it decides the size of the registry
    and how the panel is updated, so changing it is a delete-and-add
    operation. The controller is offered, because moving a panel to another
    player is a remapping like any other and used to require deleting the
    panel and pairing the tablet again.

    Both are one form. A panel has little enough to configure that a menu only
    added clicks, and options are stored whole, so one submission writes the
    source and the registry together rather than each branch having to write
    the half it did not ask about.
    """

    # Read once from the entry, by _async_load, and then edited in place by
    # the mixin. Never mutated through these class attributes.
    _registry: list[RegistryEntry] = []
    _retired: list[str] = []
    _loaded: bool = False

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Enter at the step every options flow has to start from."""
        return await self.async_step_panel_init(user_input)

    async def async_step_panel_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Show the whole of a panel's configuration on one page.

        The step is `panel_init` rather than `init`: both options flows of
        this domain start at `async_step_init`, and a shared step ID would
        make them share a title and a description too. It is a real step and
        not merely a step ID passed to the form, because Home Assistant
        re-runs the shown step by name when the dialog is opened.
        """
        self._async_load()
        return await self.async_step_entities(user_input)

    @callback
    def _registry_step_id(self) -> str:
        """Render and translate the registry form as the panel's own page."""
        return "panel_init"

    @callback
    def _registry_extra_fields(self) -> dict[Any, Any]:
        """Ask for the source above the groups, on the same page."""
        return {
            vol.Required(
                CONF_CONTROLLER_ENTRY_ID
            ): _controller_selector(self.hass),
        }

    @callback
    def _registry_extra_suggested(self) -> dict[str, Any]:
        """Start the source field on the source in use."""
        return {CONF_CONTROLLER_ENTRY_ID: self._controller_entry_id()}

    @callback
    def _registry_extra_placeholders(self) -> dict[str, str]:
        """Name the panel being configured."""
        return {"name": self.config_entry.title}

    @callback
    def _async_load(self) -> None:
        """Read the stored registry once, before anything edits it."""
        if self._loaded:
            return
        entry = self.config_entry
        self._profile = panel_profile(entry.data.get(CONF_PROFILE))
        source = (
            entry.options if CONF_ENTITIES in entry.options else entry.data
        )
        self._registry = stored_entries(source, CONF_ENTITIES)
        self._retired = stored_retired_rids(source, CONF_RETIRED_RIDS)
        self._loaded = True

    @callback
    def _controller_entry_id(self) -> str:
        """Return the source this panel currently plays from."""
        entry = self.config_entry
        return entry.options.get(
            CONF_CONTROLLER_ENTRY_ID,
            entry.data.get(CONF_CONTROLLER_ENTRY_ID, ""),
        )

    @callback
    def _options(self, controller_entry_id: str) -> dict[str, Any]:
        """Build the whole options mapping from both halves."""
        return {
            CONF_CONTROLLER_ENTRY_ID: controller_entry_id,
            CONF_ENTITIES: self._stored_registry(),
            CONF_RETIRED_RIDS: list(self._retired),
        }

    async def _async_registry_done(
        self,
        user_input: Mapping[str, Any],
    ) -> ConfigFlowResult:
        """Store both halves of the page and reload the panel."""
        controller_entry_id = (
            user_input.get(CONF_CONTROLLER_ENTRY_ID)
            or self._controller_entry_id()
        )
        return self.async_create_entry(
            data=self._options(str(controller_entry_id))
        )
