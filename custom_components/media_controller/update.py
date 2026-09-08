"""Offering a panel a firmware it can install without a cable.

A paired ESP32 panel goes on a wall, and until now the only way to move it to
a newer build was to take it off the wall and plug it into a laptop. In
practice that means it is never updated, and no firmware fix — including a
security one — reaches an installed device.

This entity is the other half of that. It appears under Settings → Updates,
where people already look, and it says three things:

* **what is on the panel**, from the panel's own status report and nothing
  else. Not what was current when it was paired, not what the installer page
  offers today — what the device says it is running;
* **what it could be on**, from the release index the web installer
  publishes, and only builds this integration already understands. A firmware
  built against a newer contract would install perfectly and then ignore half
  of what Home Assistant sends it, so it is not offered until the integration
  is upgraded. That is the compatibility half of the question, and it is why
  a firmware release is not simply "the newest file on the page";
* **whether an install is under way**, which is a window rather than a
  measurement: the device answers nothing at all while it writes flash.

Pressing Install downloads the image *in Home Assistant*, checks it against
its published SHA-256, and only then tells the panel a version is waiting. A
build that fails that check is never offered to the device, and the person
who pressed the button is told why. See `panel_firmware.py` for the endpoints
the panel then calls, and `firmware_release.py` for the rules.

Only clients that can actually be updated this way get one. The T560 tablet
is deployed over SSH and is a different problem; it keeps the repair issue in
`compatibility.py`, which is the only thing that ever told anybody a panel
was behind.
"""

from __future__ import annotations

import logging

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_PROFILE, INSTALLER_URL
from .firmware_release import FirmwareRelease
from .panel_entity import PanelEntity
from .panel_firmware import FirmwareUnavailable, async_firmware_index
from .profiles import UPDATE_KIND_FIRMWARE, panel_profile

_LOGGER = logging.getLogger(__name__)

# Where the update procedure and the USB recovery path are written down. It
# is the fallback when a release names no notes of its own, so the link on
# the entity always leads somewhere useful.
DOCUMENTATION_URL = (
    "https://github.com/VahaC/ha-media-controller/blob/main/docs/"
    "ESP32_PAIRED_CONTROLLER.md"
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the firmware update entity of one panel, where there is one."""
    runtime = entry.runtime_data
    if not hasattr(runtime, "state"):
        return
    profile = panel_profile(entry.data.get(CONF_PROFILE))
    if profile.update_kind != UPDATE_KIND_FIRMWARE:
        # A tablet is rebuilt and copied over SSH. An entity with an Install
        # button that cannot install anything would be worse than no entity.
        return
    async_add_entities([PanelFirmwareUpdate(hass, entry, runtime)])


class PanelFirmwareUpdate(PanelEntity, UpdateEntity):
    """The firmware a panel is on, and the one it could be on."""

    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_supported_features = UpdateEntityFeature.INSTALL

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        runtime: object,
    ) -> None:
        """Initialize the firmware update entity."""
        super().__init__(entry, runtime, "firmware")
        # The index is shared by every panel in the installation: two of them
        # moving to the same build download it once.
        self._index = async_firmware_index(hass)

    async def async_added_to_hass(self) -> None:
        """Follow the panel's reports and the published release index."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._index.add_listener(self._async_index_changed)
        )

    @callback
    def _async_index_changed(self) -> None:
        """Redraw when what is published changes."""
        self.async_write_ha_state()

    # ------------------------------------------------------------- reading

    @property
    def _offer(self) -> FirmwareRelease | None:
        """Return the build this panel should be offered, if any."""
        return self._index.offer(
            self.installed_version or "", self._panel.status.contract_version
        )

    @property
    def installed_version(self) -> str | None:
        """Return the build the panel last reported, or None.

        A panel that has never reported is `None` rather than a guess. It is
        also the reason nothing is ever offered to one: there is no version
        to compare against, and a firmware installed on that basis could be
        older than what is already on the device.
        """
        return self._panel.status.app_version or None

    @property
    def latest_version(self) -> str | None:
        """Return the newest compatible build, or what is installed.

        `None` while the release index has never been read: an installation
        with no route to the internet must not be told its panel is up to
        date on the strength of never having looked.
        """
        if not self._index.loaded:
            return None
        offer = self._offer
        return offer.version if offer is not None else self.installed_version

    @property
    def in_progress(self) -> bool:
        """Return whether an install asked for is still plausibly running."""
        return self._panel.update_in_progress()

    @property
    def release_url(self) -> str | None:
        """Return where to read about the build being offered."""
        offer = self._offer
        if offer is not None and offer.release_url:
            return offer.release_url
        return DOCUMENTATION_URL

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose why a newer build is not being offered, when one exists.

        Held back by the contract check is the one case that would otherwise
        look like a bug: the installer page shows a newer version, and Home
        Assistant offers nothing. The answer is that the integration has to
        be upgraded first, and this is where it says so.
        """
        attributes: dict[str, object] = {"installer_url": INSTALLER_URL}
        if not self._index.loaded or not self._index.releases:
            return attributes
        newest = self._index.releases[0]
        offer = self._offer
        if offer is None and newest.version != self.installed_version:
            attributes["held_back_version"] = newest.version
            attributes["held_back_contract_version"] = newest.contract_version
        return attributes

    # ----------------------------------------------------------- installing

    async def async_install(
        self,
        version: str | None,
        backup: bool,
        **kwargs: object,
    ) -> None:
        """Verify the image, then tell the panel a version is waiting.

        The download happens here, in Home Assistant, and it happens before
        the panel is told anything. That ordering is the point: an image that
        cannot be fetched, or whose bytes do not match the SHA-256 the
        release index publishes, produces an error in front of the person who
        pressed the button and no traffic to the device at all.

        Nothing is pushed after that. The version travels in the config
        sensor like every other command, and the panel acts on it the next
        time it polls — which also means a panel that is asleep, or off the
        network, installs when it comes back rather than losing the request.
        """
        offer = self._offer
        if offer is None:
            raise HomeAssistantError(
                "There is no newer firmware this version of Media Controller "
                "can install on this panel."
            )
        if version is not None and version != offer.version:
            raise HomeAssistantError(
                f"Firmware {version} is not the build being offered "
                f"({offer.version})."
            )

        try:
            await self._index.async_prepare(offer)
        except FirmwareUnavailable as err:
            _LOGGER.error("Refusing to install firmware %s: %s", offer.version, err)
            raise HomeAssistantError(str(err)) from err

        if not self._panel.request_update(offer.version):
            raise HomeAssistantError(
                f"Firmware {offer.version} is not a version this panel can "
                "be asked for."
            )
        _LOGGER.info(
            "Panel %s is asked to install firmware %s",
            self._entry.title,
            offer.version,
        )
        self.async_write_ha_state()
