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
that a device serves it with nothing outside the house involved.
"""

import gzip
from pathlib import Path

import esphome.codegen as cg
from esphome.components import web_server_base
from esphome.components.web_server_base import CONF_WEB_SERVER_BASE_ID
import esphome.config_validation as cv
from esphome.const import CONF_ID, CONF_PORT, PLATFORM_ESP32
from esphome.core import coroutine_with_priority
from esphome.coroutine import CoroPriority
from esphome.types import ConfigType

CODEOWNERS = ["@VahaC"]
DEPENDENCIES = ["network"]
AUTO_LOAD = ["json", "web_server_base"]

CONF_SKINS = "skins"
CONF_RAW_DATA_ID = "raw_data_id"

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
    the page fetches the document and three JSON routes at once.
    """
    from esphome.components import socket

    socket.consume_sockets(3, "media_controller_grid")(config)
    return config


FINAL_VALIDATE_SCHEMA = _final_validate


def _editor_bytes() -> bytes:
    """Return the editor page, gzipped.

    `mtime=0` so that an unchanged page produces an unchanged array and does
    not rewrite the build directory on every run.
    """
    source = Path(__file__).parent / "editor.html"
    return gzip.compress(source.read_bytes(), compresslevel=9, mtime=0)


@coroutine_with_priority(CoroPriority.WEB)
async def to_code(config: ConfigType) -> None:
    base = await cg.get_variable(config[CONF_WEB_SERVER_BASE_ID])

    var = cg.new_Pvariable(config[CONF_ID], base)
    await cg.register_component(var, config)
    cg.add(var.set_port(config[CONF_PORT]))
    for skin in config[CONF_SKINS]:
        cg.add(var.add_skin(skin))

    page = _editor_bytes()
    array = cg.progmem_array(config[CONF_RAW_DATA_ID], list(page))
    cg.add(var.set_editor(array, len(page)))
