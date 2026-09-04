"""The room-control grid of the paired ESP32-S3 firmware, and its editor.

This is an ESPHome external component rather than more YAML because two parts
of it cannot be written as lambdas: a POD written to NVS through
`make_preference`, and an `AsyncWebHandler` registered on `web_server_base`.
Everything it knows is in `media_controller_grid.h`; everything that reaches
Home Assistant is installed into it from `firmware/media-controller-paired.yaml`
and lives there.

**Only the paired firmware uses it.** The classic firmware resolves entity IDs
while compiling, in both directions, so it can never be handed a card at
runtime; that is a property of the variant, not a gap. See
`docs/ESP32_PAIRED_CONTROLLER.md`.

The editor is one HTML file, gzipped at codegen time and linked into flash, so
that a device serves it with nothing outside the house involved. The skin
previews beside it travel the same way and for the same reason, one small PNG
per configured skin.
"""

import gzip
from pathlib import Path
import re

import esphome.codegen as cg
from esphome.components import web_server_base
from esphome.components.web_server_base import CONF_WEB_SERVER_BASE_ID
import esphome.config_validation as cv
from esphome.const import CONF_ID, CONF_PORT, PLATFORM_ESP32
from esphome.core import ID, coroutine_with_priority
from esphome.coroutine import CoroPriority
from esphome.types import ConfigType

CODEOWNERS = ["@VahaC"]
DEPENDENCIES = ["network"]
AUTO_LOAD = ["json", "web_server_base"]

CONF_SKINS = "skins"
CONF_RAW_DATA_ID = "raw_data_id"

# Where a skin's picture is looked for, named after the skin itself. A skin
# configured with no file here simply gets no preview: the editor then shows
# its name alone, which is still a usable choice.
PREVIEW_DIRECTORY = "previews"

media_controller_grid_ns = cg.esphome_ns.namespace("media_controller_grid")
MediaControllerGrid = media_controller_grid_ns.class_(
    "MediaControllerGrid", cg.Component
)

CONFIG_SCHEMA = cv.All(
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(MediaControllerGrid),
            cv.GenerateID(CONF_WEB_SERVER_BASE_ID): cv.use_id(
                web_server_base.WebServerBase
            ),
            cv.Optional(CONF_PORT, default=80): cv.port,
            # The layouts the interface draws, in the spelling docs/CONTRACT.md
            # uses. They are configured rather than hard-coded in C++ because
            # which layouts exist is the interface's business: this component
            # only has to refuse a name that is not one of them before it is
            # passed on to Home Assistant.
            cv.Optional(CONF_SKINS, default=[]): cv.ensure_list(cv.string_strict),
            cv.GenerateID(CONF_RAW_DATA_ID): cv.declare_id(cg.uint8),
        }
    ).extend(cv.COMPONENT_SCHEMA),
    cv.only_on([PLATFORM_ESP32]),
)


def _final_validate(config: ConfigType) -> ConfigType:
    """Account for the sockets a browser opens against the editor.

    The listening socket itself belongs to `web_server_base` and is registered
    there. These are the concurrent connections on top of it: a phone opening
    the page fetches the document and three JSON routes at once, and then one
    skin preview per skin the device draws.
    """
    from esphome.components import socket

    socket.consume_sockets(
        max(3, len(config[CONF_SKINS])), "media_controller_grid"
    )(config)
    return config


FINAL_VALIDATE_SCHEMA = _final_validate


def _editor_bytes() -> bytes:
    """Return the editor page, gzipped.

    `mtime=0` so that an unchanged page produces an unchanged array and does
    not rewrite the build directory on every run.
    """
    source = Path(__file__).parent / "editor.html"
    return gzip.compress(source.read_bytes(), compresslevel=9, mtime=0)


def _identifier(skin: str) -> str:
    """Return a skin name reduced to something a C identifier may contain."""
    return re.sub(r"\W", "_", skin)


def _previews() -> dict[str, Path]:
    """Return the preview pictures this checkout carries, keyed by skin.

    The directory is listed and the name matched against what is in it,
    rather than a path being composed from the configured skin name: a skin
    name is free text from YAML, and building a filename out of one would let
    it point anywhere.
    """
    directory = Path(__file__).parent / PREVIEW_DIRECTORY
    if not directory.is_dir():
        return {}
    return {source.stem: source for source in directory.glob("*.png")}


def _preview_bytes(previews: dict[str, Path], skin: str) -> bytes | None:
    """Return one skin's preview picture, or None when this build has none.

    Deliberately **not** gzipped, unlike the editor beside it: a PNG is
    already deflate-compressed, and wrapping one in a gzip member makes it
    about twenty bytes larger while costing the device a decompression it
    does not need. The pictures are kept small where it actually pays —
    downsampled and quantised to a palette by tools/make-skin-previews.py.
    """
    source = previews.get(skin)
    return None if source is None else source.read_bytes()


@coroutine_with_priority(CoroPriority.WEB)
async def to_code(config: ConfigType) -> None:
    base = await cg.get_variable(config[CONF_WEB_SERVER_BASE_ID])

    var = cg.new_Pvariable(config[CONF_ID], base)
    await cg.register_component(var, config)
    cg.add(var.set_port(config[CONF_PORT]))
    previews = _previews()
    for index, skin in enumerate(config[CONF_SKINS]):
        cg.add(var.add_skin(skin))
        # What the skin looks like, shown beside the list in the editor. A
        # skin with no picture is registered as a skin all the same: the
        # editor falls back to its name, which is still a usable choice.
        if (preview := _preview_bytes(previews, skin)) is None:
            continue
        # A skin name is the client's own vocabulary and need not be a C
        # identifier, so the array is numbered and the name only decorates
        # it. `set_preview` below is where the two are actually tied.
        preview_id = ID(
            f"media_controller_grid_preview_{index}_{_identifier(skin)}",
            is_declaration=True,
            type=cg.uint8,
        )
        cg.add(
            var.set_preview(
                skin,
                cg.progmem_array(preview_id, list(preview)),
                len(preview),
            )
        )

    page = _editor_bytes()
    array = cg.progmem_array(config[CONF_RAW_DATA_ID], list(page))
    cg.add(var.set_editor(array, len(page)))
