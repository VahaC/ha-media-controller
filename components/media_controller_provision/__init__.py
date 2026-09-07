"""The endpoint Home Assistant hands a panel its bootstrap over.

The paired firmware has always been able to *ask* Home Assistant for a token,
which works only for a device that already knows where Home Assistant is. A
factory image knows nothing: it is one binary flashed from a web page onto any
number of boards, and baking an address into it would make it personal again.

So the direction is reversed. The device announces itself over mDNS, Home
Assistant finds it, a person types the six digits the screen is showing, and
Home Assistant posts the address, the token and the config entity to this
endpoint. Nothing personal is ever compiled in, and the Wi-Fi credentials that
got the device onto the network never leave the browser that flashed it.

This is an external component rather than YAML for the same reason
`media_controller_grid` next to it is: an `AsyncWebHandler` on
`web_server_base` cannot be written as a lambda. It shares that listener, so a
device still opens exactly one port.

**This component knows nothing about Home Assistant.** It holds no URL, mints
nothing and calls nothing. What it does is check a code against a rate limit
and hand three strings to a `std::function` the firmware YAML installs at
boot — the same seam `firmware/media-controller-ui.yaml` describes.
"""

import esphome.codegen as cg
from esphome.components import web_server_base
from esphome.components.web_server_base import CONF_WEB_SERVER_BASE_ID
import esphome.config_validation as cv
from esphome.const import CONF_ID, CONF_PORT, CONF_VERSION, PLATFORM_ESP32
from esphome.core import coroutine_with_priority
from esphome.coroutine import CoroPriority
from esphome.types import ConfigType

CODEOWNERS = ["@VahaC"]
DEPENDENCIES = ["network"]
AUTO_LOAD = ["json", "web_server_base"]

CONF_PROFILE = "profile"
CONF_PANEL_NAME = "panel_name"
CONF_CONTRACT_VERSION = "contract_version"

media_controller_provision_ns = cg.esphome_ns.namespace(
    "media_controller_provision"
)
MediaControllerProvision = media_controller_provision_ns.class_(
    "MediaControllerProvision", cg.Component
)

CONFIG_SCHEMA = cv.All(
    cv.Schema(
        {
            cv.GenerateID(): cv.declare_id(MediaControllerProvision),
            cv.GenerateID(CONF_WEB_SERVER_BASE_ID): cv.use_id(
                web_server_base.WebServerBase
            ),
            cv.Optional(CONF_PORT, default=80): cv.port,
            # What the discovery record already says about this device, so
            # that Home Assistant can confirm it is talking to the panel it
            # found rather than to whatever else answers on that address.
            cv.Required(CONF_PROFILE): cv.string_strict,
            cv.Required(CONF_PANEL_NAME): cv.string_strict,
            cv.Required(CONF_CONTRACT_VERSION): cv.positive_int,
            cv.Required(CONF_VERSION): cv.string_strict,
        }
    ).extend(cv.COMPONENT_SCHEMA),
    cv.only_on([PLATFORM_ESP32]),
)


def _final_validate(config: ConfigType) -> ConfigType:
    """Reserve the sockets Home Assistant opens against this endpoint.

    Two: Home Assistant asks what the device is and then posts the bootstrap,
    and a retry may overlap the request it is replacing. The listener itself
    belongs to `web_server_base` and is counted there.
    """
    from esphome.components import socket

    socket.consume_sockets(2, "media_controller_provision")(config)
    return config


FINAL_VALIDATE_SCHEMA = _final_validate


@coroutine_with_priority(CoroPriority.WEB)
async def to_code(config: ConfigType) -> None:
    base = await cg.get_variable(config[CONF_WEB_SERVER_BASE_ID])

    var = cg.new_Pvariable(config[CONF_ID], base)
    await cg.register_component(var, config)
    cg.add(var.set_port(config[CONF_PORT]))
    cg.add(var.set_profile(config[CONF_PROFILE]))
    cg.add(var.set_panel_name(config[CONF_PANEL_NAME]))
    cg.add(var.set_contract_version(config[CONF_CONTRACT_VERSION]))
    cg.add(var.set_firmware_version(config[CONF_VERSION]))
