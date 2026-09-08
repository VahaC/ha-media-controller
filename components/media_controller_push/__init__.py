"""Where Home Assistant posts a state this device would otherwise have polled.

The paired firmware read the player and its own configuration by asking, once
a second each, over `http_request` -- which is synchronous, so each ask stopped
the main loop for the length of a connection, a transfer and a parse. On a
board whose RGB display is refreshed by the processor itself out of PSRAM,
that is not a background cost: it is a picture that visibly jumps twice a
second. See the header of `media_controller_push.h` for the mechanism.

So the two payloads travel the other way now. Home Assistant posts them when
they change, the poll behind them becomes a fallback for whatever a push
missed, and a paused player costs nothing at all.

This is an external component rather than YAML for the same reason
`media_controller_provision` and `media_controller_grid` beside it are: an
`AsyncWebHandler` on `web_server_base` cannot be written as a lambda. It shares
that listener, so a device still opens exactly one port.

**This component knows nothing about Home Assistant and does not read the
documents it carries.** It checks the key, caps the size, and hands the body to
a `std::function` the firmware YAML installs at boot -- the same seam
`firmware/media-controller-ui.yaml` describes. The parsers behind that seam are
the ones the polls already use, so each payload is read in one place.
"""

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
AUTO_LOAD = ["web_server_base"]

media_controller_push_ns = cg.esphome_ns.namespace("media_controller_push")
MediaControllerPush = media_controller_push_ns.class_(
    "MediaControllerPush", cg.Component
)

CONFIG_SCHEMA = cv.All(
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(MediaControllerPush),
            cv.GenerateID(CONF_WEB_SERVER_BASE_ID): cv.use_id(
                web_server_base.WebServerBase
            ),
            cv.Optional(CONF_PORT, default=80): cv.port,
        }
    ).extend(cv.COMPONENT_SCHEMA),
    cv.only_on([PLATFORM_ESP32]),
)


def _final_validate(config: ConfigType) -> ConfigType:
    """Reserve the sockets Home Assistant opens against these routes.

    Two: the player and the configuration are pushed by separate listeners on
    the Home Assistant side and a change to both at once is ordinary -- a track
    that starts because somebody pressed a button on the panel moves the player
    and the configuration in the same instant. The listener itself belongs to
    `web_server_base` and is counted there.
    """
    from esphome.components import socket

    socket.consume_sockets(2, "media_controller_push")(config)
    return config


FINAL_VALIDATE_SCHEMA = _final_validate


@coroutine_with_priority(CoroPriority.WEB)
async def to_code(config: ConfigType) -> None:
    base = await cg.get_variable(config[CONF_WEB_SERVER_BASE_ID])

    var = cg.new_Pvariable(config[CONF_ID], base)
    await cg.register_component(var, config)
    cg.add(var.set_port(config[CONF_PORT]))
