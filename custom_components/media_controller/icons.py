"""The endpoints a client reads card artwork from.

Two routes, and both of them are deliberately dull:

```text
GET /api/media_controller/icons                     the catalog, no images
GET /api/media_controller/icon/<icon_id>/<size>     one pre-rendered variant
GET /api/media_controller/icon/<icon_id>/png        the source artwork
```

The catalog is a separate request and **not a block on the config sensor**, for
exactly the reason the layout backup is not one: panels poll that sensor about
once a second, and a list that changes when the integration is upgraded has no
business travelling down that channel. A client reads the catalog when its
`revision` moves and otherwise never asks again.

What guards these routes:

* **authentication is the ordinary one.** `HomeAssistantView` requires a token
  by default, and a panel already holds the one Home Assistant minted for it
  when it paired. Nothing here is public, and no token is ever handed to a
  browser: the editor page a panel serves asks its own device for pictures,
  and the device answers out of what it has already downloaded;
* **an identifier is a key, never a path.** `icon_catalog.find_icon` answers
  with a catalog record or with nothing, and the filename is built from the
  record. A request for `..%2f..%2fsecrets.yaml` does not match the identifier
  pattern, is not in the catalog, and never reaches the filesystem;
* **the size is a closed vocabulary.** A variant this build publishes, or a
  404. There is no code path that renders anything on demand.

Nothing here decodes, scales or re-encodes an image. Both variants are files
shipped with the integration, built by `tools/make-icon-assets.py`, so a Home
Assistant installation needs no image library for any of this to work.
"""

from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .icon_catalog import (
    ASSET_DIRECTORY,
    ESP32_ASSET_DIRECTORY,
    PNG_VARIANT,
    catalog_payload,
    find_icon,
    is_supported_size,
)

_LOGGER = logging.getLogger(__name__)

CATALOG_URL = "/api/media_controller/icons"
# `variant` is a size in pixels or the literal `png`. It is one path segment
# and it is matched against a closed vocabulary before anything is opened.
ASSET_URL = "/api/media_controller/icon/{icon_id}/{variant}"

STATUS_UNKNOWN_ICON = "unknown_icon"
STATUS_UNKNOWN_VARIANT = "unknown_variant"
STATUS_MISSING_ASSET = "missing_asset"

# The pre-rendered variant is not an image file and must not be sniffed as
# one. It is the exact bytes an ESP32 hands to LVGL.
ESP32_CONTENT_TYPE = "application/octet-stream"
PNG_CONTENT_TYPE = "image/png"

# Both variants change only when the integration is upgraded, so a client that
# has one may keep it. The catalog carries a revision for the same purpose, and
# this is what saves the requests in between.
ASSET_CACHE_CONTROL = "public, max-age=86400"


def _asset_root() -> Path:
    """Return the directory the shipped artwork lives in."""
    return Path(__file__).parent / ASSET_DIRECTORY


class IconCatalogView(HomeAssistantView):
    """Publish which icons exist, without publishing any of the pictures."""

    url = CATALOG_URL
    name = "api:media_controller:icons"

    async def get(self, request: web.Request) -> web.Response:
        """Return the catalog document and its revision."""
        return self.json(catalog_payload())


class IconAssetView(HomeAssistantView):
    """Serve one published variant of one published icon."""

    url = ASSET_URL
    name = "api:media_controller:icon"

    def __init__(self, hass: HomeAssistant) -> None:
        """Hold the objects a request needs; there is one view per setup."""
        self._hass = hass

    async def get(
        self,
        request: web.Request,
        icon_id: str,
        variant: str,
    ) -> web.Response:
        """Return one icon file, or refuse without touching the filesystem.

        The order matters and is the whole of the path-traversal defence: the
        identifier is resolved to a catalog record first, the variant to a
        published size second, and only then is a name built out of the two
        values this module already trusts.
        """
        icon = find_icon(icon_id)
        if icon is None:
            return self.json(
                {"status": STATUS_UNKNOWN_ICON}, status_code=404
            )

        root = _asset_root()
        if variant == PNG_VARIANT:
            path = root / icon.png_name
            content_type = PNG_CONTENT_TYPE
        elif is_supported_size(variant):
            path = (
                root / ESP32_ASSET_DIRECTORY / icon.esp32_name(int(variant))
            )
            content_type = ESP32_CONTENT_TYPE
        else:
            return self.json(
                {"status": STATUS_UNKNOWN_VARIANT}, status_code=404
            )

        try:
            payload = await self._hass.async_add_executor_job(
                path.read_bytes
            )
        except OSError:
            # A file the catalog names and the installation does not carry.
            # It is a packaging fault rather than a bad request, and a client
            # treats it exactly as it treats an unreachable Home Assistant:
            # it draws its own fallback and carries on.
            _LOGGER.warning("Icon asset %s is missing", path.name)
            return self.json(
                {"status": STATUS_MISSING_ASSET}, status_code=404
            )

        return web.Response(
            body=payload,
            content_type=content_type,
            headers={"Cache-Control": ASSET_CACHE_CONTROL},
        )


def async_setup_icon_endpoints(hass: HomeAssistant) -> None:
    """Register the catalog and the asset route."""
    hass.http.register_view(IconCatalogView())
    hass.http.register_view(IconAssetView(hass))
