"""The two devices this integration registers.

A source and a panel are both devices on the integration page, and neither is
hardware this integration talks to directly: a source is the binding to one
Music Assistant player, and a panel is a client that reads it. The panel is
registered under the source it plays from, so the two appear related rather
than as two unconnected devices that happen to share an integration.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN
from .profiles import ClientProfile

# A source is not hardware. What this integration adds is the binding to one
# Music Assistant player, which is why it is registered as a service and
# appears apart from the panels on the integration page.
CONTROLLER_MODEL = "Media player source"


def controller_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return the service shared by the source's own entities."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="VahaC",
        model=CONTROLLER_MODEL,
        entry_type=DeviceEntryType.SERVICE,
    )


def panel_device_info(
    entry: ConfigEntry,
    controller_entry: ConfigEntry,
    profile: ClientProfile,
) -> DeviceInfo:
    """Return the device of one panel client."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="VahaC",
        model=profile.name,
        via_device=(DOMAIN, controller_entry.entry_id),
    )
