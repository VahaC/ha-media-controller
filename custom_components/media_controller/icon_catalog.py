"""The card artwork the integration owns, and the rules for serving it.

Card icons used to be compiled into each client. The ESP32 firmware carried
six pictures and stored a card's choice as a **1-based index into that array**,
so the artwork could only grow by reflashing every device in the house, and
reordering the array would have silently moved everybody's icons. This module
is the other half of that decision: the catalog lives here, a card stores a
**stable string identifier**, and a client downloads the picture it needs.

Three rules carry the module, and every one of them is a security rule as much
as a correctness one:

* **an identifier is validated, then used as a key — never as a path.** A
  request names an icon; this module answers with a catalog record or with
  nothing. The filename is built from the record, so `../../secrets.yaml`
  cannot become a filename however it is spelled, encoded or escaped;
* **the size is a closed vocabulary.** A client asks for a variant this build
  publishes or it is refused. That is what keeps the ESP32 from being handed a
  picture it would have to scale at draw time, which this LVGL build cannot do
  at all — see AGENTS.md;
* **the identifier is not the order.** `ICONS` is a tuple because a tuple reads
  in a fixed order in the editor, but nothing anywhere stores the position of
  an entry in it. Adding, removing or reordering a row cannot change what a
  card already points at.

This module deliberately has no Home Assistant imports, so all of that can be
tested without a Home Assistant runtime. The endpoints that serve it live in
`icons.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
import zlib

# An icon identifier: lowercase, digits and hyphens, starting with a letter or
# a digit. It is deliberately narrower than a filename needs to be — no dots,
# no slashes, no percent signs, no upper case — so that a value which passes
# this cannot express a path, an extension or a case-folding trick even before
# it is looked up in the catalog below.
ICON_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")

# The card size the ESP32 draws, in pixels. The firmware asks for exactly this
# and blits it without transforming it: this build sets LV_COLOR_16_SWAP and
# leaves LV_DRAW_SW_SUPPORT_SWAPPED off, so LVGL's software renderer cannot
# scale or rotate a source at all. Serving the exact size is not an
# optimisation here, it is the only thing that works.
ESP32_ICON_SIZE = 40

# Every variant a client may ask for. A request naming anything else is
# refused rather than rendered: an open size parameter would be an invitation
# to ask for 4096 and find out what the device does with 64 MB.
SUPPORTED_SIZES: tuple[int, ...] = (ESP32_ICON_SIZE,)

# The ESP32 variant is not an image file. It is the exact bytes LVGL draws:
# ARGB8888, which is what `type: RGB` with `transparency: alpha_channel`
# already produces for the artwork compiled into the firmware, in the same
# little-endian B, G, R, A order. A device therefore needs no PNG decoder, no
# decode buffer and no guesswork; it checks eight bytes of header and points
# an `lv_image_dsc_t` at the rest.
ESP32_MAGIC = b"MCI1"
ESP32_HEADER_BYTES = 8
ESP32_BYTES_PER_PIXEL = 4

# What one variant weighs, header included. A client uses it to size its
# response buffer and to refuse a truncated download without parsing anything.
ESP32_VARIANT_BYTES = (
    ESP32_HEADER_BYTES
    + ESP32_ICON_SIZE * ESP32_ICON_SIZE * ESP32_BYTES_PER_PIXEL
)

# The browser variant. It is the source artwork, served to the small editor
# page a panel hosts on the device itself, so that a person choosing an icon
# sees the icon rather than its name.
PNG_VARIANT = "png"

# Where the files live, relative to the integration folder. Both are ordinary
# package data; nothing here is generated at runtime, so no image library is
# needed in a Home Assistant installation.
ASSET_DIRECTORY = "icons"
ESP32_ASSET_DIRECTORY = "esp32"


@dataclass(frozen=True, slots=True)
class CatalogIcon:
    """One piece of card artwork the integration publishes."""

    # Stable for the life of the catalog. It is what a card stores, what a
    # layout document written years ago still names, and what the two clients
    # already carried as the names of their compiled-in artwork — so every
    # icon a user has already chosen maps to itself and nothing migrates.
    icon_id: str
    # What the editor calls it. It may be changed freely: no client stores it
    # and nothing compares it.
    label: str

    def as_payload(self) -> dict[str, Any]:
        """Return the catalog row a client reads."""
        return {"id": self.icon_id, "label": self.label}

    @property
    def png_name(self) -> str:
        """Return the source file name, built from the identifier only."""
        return f"{self.icon_id}.png"

    def esp32_name(self, size: int) -> str:
        """Return the pre-rendered file name for one supported size."""
        return f"{self.icon_id}-{size}.bin"


# The catalog. Adding a row here, with its two asset files beside it, is the
# whole of adding an icon: no client is rebuilt, no device is reflashed, and
# no identifier already in use changes meaning.
#
# The first eight identifiers are the artwork the two clients used to carry
# compiled in, under exactly the names their layout documents already use.
# That is deliberate: a card that says `blind` today keeps saying `blind`, and
# the migration for existing layouts is that there is none.
#
# The rest is the standard home set, drawn by
# `clients/t560/tools/make-room-icons.py`,
# `clients/t560/tools/make-home-icons.py` and
# `clients/t560/tools/make-smart-icons.py` in the same alpha-mask style: one
# glyph per everyday home device, so every registry group has something to
# choose from.
ICONS: tuple[CatalogIcon, ...] = (
    CatalogIcon("light-1", "Lamp"),
    CatalogIcon("light-2", "Two lamps"),
    CatalogIcon("desk-lamp", "Desk lamp"),
    CatalogIcon("desk-led-strip", "LED strip"),
    CatalogIcon("fan", "Fan"),
    CatalogIcon("ac", "Air conditioner"),
    CatalogIcon("blind", "Blind"),
    CatalogIcon("weather", "Weather"),
    CatalogIcon("bulb", "Bulb"),
    CatalogIcon("ceiling-lamp", "Ceiling lamp"),
    CatalogIcon("floor-lamp", "Floor lamp"),
    CatalogIcon("wall-lamp", "Wall lamp"),
    CatalogIcon("plug", "Plug"),
    CatalogIcon("tv", "TV"),
    CatalogIcon("speaker", "Speaker"),
    CatalogIcon("camera", "Camera"),
    CatalogIcon("bell", "Doorbell"),
    CatalogIcon("thermometer", "Thermometer"),
    CatalogIcon("thermostat", "Thermostat"),
    CatalogIcon("heater", "Heater"),
    CatalogIcon("curtain", "Curtain"),
    CatalogIcon("garage", "Garage door"),
    CatalogIcon("sun", "Sun"),
    CatalogIcon("moon", "Moon"),
    CatalogIcon("cloud", "Cloud"),
    CatalogIcon("rain", "Rain"),
    CatalogIcon("snow", "Snow"),
    CatalogIcon("motion", "Motion"),
    CatalogIcon("door", "Door"),
    CatalogIcon("window", "Window"),
    CatalogIcon("lock", "Lock"),
    CatalogIcon("battery", "Battery"),
    CatalogIcon("chandelier", "Chandelier"),
    CatalogIcon("pendant-lamp", "Pendant lamp"),
    CatalogIcon("lantern", "Lantern"),
    CatalogIcon("flashlight", "Flashlight"),
    CatalogIcon("spotlight", "Spotlight"),
    CatalogIcon("string-light", "String lights"),
    CatalogIcon("candle", "Candle"),
    CatalogIcon("lamp-shade", "Lampshade"),
    CatalogIcon("night-light", "Night light"),
    CatalogIcon("track-light", "Track light"),
    CatalogIcon("garden-light", "Garden light"),
    CatalogIcon("disco-ball", "Disco ball"),
    CatalogIcon("lamp-post", "Lamp post"),
    CatalogIcon("socket", "Socket"),
    CatalogIcon("power", "Power"),
    CatalogIcon("toggle", "Toggle switch"),
    CatalogIcon("dimmer", "Dimmer"),
    CatalogIcon("double-switch", "Double switch"),
    CatalogIcon("remote", "Remote"),
    CatalogIcon("timer", "Timer"),
    CatalogIcon("power-strip", "Power strip"),
    CatalogIcon("charger", "Charger"),
    CatalogIcon("button", "Button"),
    CatalogIcon("breaker", "Circuit breaker"),
    CatalogIcon("ceiling-fan", "Ceiling fan"),
    CatalogIcon("air-purifier", "Air purifier"),
    CatalogIcon("humidifier", "Humidifier"),
    CatalogIcon("dehumidifier", "Dehumidifier"),
    CatalogIcon("vent", "Vent"),
    CatalogIcon("stove", "Stove"),
    CatalogIcon("humidity", "Humidity"),
    CatalogIcon("droplet", "Droplet"),
    CatalogIcon("leaf", "Leaf"),
    CatalogIcon("water-heater", "Water heater"),
    CatalogIcon("heat-pump", "Heat pump"),
    CatalogIcon("chimney", "Chimney"),
    CatalogIcon("awning", "Awning"),
    CatalogIcon("pergola", "Pergola"),
    CatalogIcon("fence", "Fence"),
    CatalogIcon("gate", "Gate"),
    CatalogIcon("shutters", "Shutters"),
    CatalogIcon("skylight", "Skylight"),
    CatalogIcon("sun-umbrella", "Sun umbrella"),
    CatalogIcon("greenhouse", "Greenhouse"),
    CatalogIcon("shed", "Shed"),
    CatalogIcon("mailbox", "Mailbox"),
    CatalogIcon("partly-cloudy", "Partly cloudy"),
    CatalogIcon("thunderstorm", "Thunderstorm"),
    CatalogIcon("fog", "Fog"),
    CatalogIcon("hail", "Hail"),
    CatalogIcon("rainbow", "Rainbow"),
    CatalogIcon("sunrise", "Sunrise"),
    CatalogIcon("starry-night", "Starry night"),
    CatalogIcon("umbrella", "Umbrella"),
    CatalogIcon("lightning", "Lightning"),
    CatalogIcon("eclipse", "Eclipse"),
    CatalogIcon("overcast", "Overcast"),
    CatalogIcon("sleet", "Sleet"),
    CatalogIcon("smoke-detector", "Smoke detector"),
    CatalogIcon("siren", "Siren"),
    CatalogIcon("alarm-clock", "Alarm clock"),
    CatalogIcon("shield", "Shield"),
    CatalogIcon("keypad", "Keypad"),
    CatalogIcon("key", "Key"),
    CatalogIcon("camera-dome", "Dome camera"),
    CatalogIcon("intercom", "Intercom"),
    CatalogIcon("leak", "Leak"),
    CatalogIcon("panic-button", "Panic button"),
    CatalogIcon("lock-open", "Unlocked"),
    CatalogIcon("safe", "Safe"),
    CatalogIcon("video-doorbell", "Video doorbell"),
    CatalogIcon("window-sensor", "Window sensor"),
    CatalogIcon("soundbar", "Soundbar"),
    CatalogIcon("projector", "Projector"),
    CatalogIcon("screen", "Screen"),
    CatalogIcon("gamepad", "Gamepad"),
    CatalogIcon("radio", "Radio"),
    CatalogIcon("microphone", "Microphone"),
    CatalogIcon("headphones", "Headphones"),
    CatalogIcon("laptop", "Laptop"),
    CatalogIcon("tablet", "Tablet"),
    CatalogIcon("phone", "Phone"),
    CatalogIcon("printer", "Printer"),
    CatalogIcon("router", "Router"),
    CatalogIcon("fridge", "Fridge"),
    CatalogIcon("oven", "Oven"),
    CatalogIcon("microwave", "Microwave"),
    CatalogIcon("kettle", "Kettle"),
    CatalogIcon("coffee-mug", "Coffee mug"),
    CatalogIcon("toaster", "Toaster"),
    CatalogIcon("cooker-hood", "Cooker hood"),
    CatalogIcon("faucet", "Faucet"),
    CatalogIcon("dishwasher", "Dishwasher"),
    CatalogIcon("blender", "Blender"),
    CatalogIcon("trash-can", "Trash can"),
    CatalogIcon("cooktop", "Cooktop"),
    CatalogIcon("shower", "Shower"),
    CatalogIcon("bathtub", "Bathtub"),
    CatalogIcon("toilet", "Toilet"),
    CatalogIcon("washer", "Washer"),
    CatalogIcon("iron", "Iron"),
    CatalogIcon("robot-vacuum", "Robot vacuum"),
    CatalogIcon("hamper", "Hamper"),
    CatalogIcon("soap-dispenser", "Soap dispenser"),
    CatalogIcon("bath-scale", "Bathroom scale"),
    CatalogIcon("towel", "Towel"),
    CatalogIcon("sofa", "Sofa"),
    CatalogIcon("armchair", "Armchair"),
    CatalogIcon("bed", "Bed"),
    CatalogIcon("chair", "Chair"),
    CatalogIcon("table", "Table"),
    CatalogIcon("desk", "Desk"),
    CatalogIcon("wardrobe", "Wardrobe"),
    CatalogIcon("shelf", "Shelf"),
    CatalogIcon("clock", "Clock"),
    CatalogIcon("books", "Books"),
    CatalogIcon("plant", "Plant"),
    CatalogIcon("crib", "Crib"),
    CatalogIcon("tree", "Tree"),
    CatalogIcon("flower", "Flower"),
    CatalogIcon("sprinkler", "Sprinkler"),
    CatalogIcon("mower", "Lawn mower"),
    CatalogIcon("grill", "Grill"),
    CatalogIcon("birdhouse", "Birdhouse"),
    CatalogIcon("planter", "Planter"),
    CatalogIcon("hose-reel", "Hose reel"),
    CatalogIcon("solar-panel", "Solar panel"),
    CatalogIcon("meter", "Meter"),
    CatalogIcon("ev-charger", "EV charger"),
    CatalogIcon("battery-charge", "Battery charging"),
    CatalogIcon("battery-low", "Low battery"),
    CatalogIcon("wind-turbine", "Wind turbine"),
    CatalogIcon("hydro", "Hydro"),
    CatalogIcon("power-pole", "Power pole"),
    CatalogIcon("downlight", "Downlight"),
    CatalogIcon("globe-lamp", "Globe lamp"),
    CatalogIcon("filament", "Filament bulb"),
    CatalogIcon("tube-light", "Tube light"),
    CatalogIcon("panel-light", "Panel light"),
    CatalogIcon("neon", "Neon sign"),
    CatalogIcon("path-light", "Path light"),
    CatalogIcon("stair-light", "Stair light"),
    CatalogIcon("pool-light", "Pool light"),
    CatalogIcon("cabinet-light", "Cabinet light"),
    CatalogIcon("vanity-light", "Vanity light"),
    CatalogIcon("picture-light", "Picture light"),
    CatalogIcon("grow-light", "Grow light"),
    CatalogIcon("emergency-light", "Emergency light"),
    CatalogIcon("rotary-dimmer", "Rotary dimmer"),
    CatalogIcon("touch-panel", "Touch panel"),
    CatalogIcon("scene-switch", "Scene switch"),
    CatalogIcon("blind-switch", "Blind switch"),
    CatalogIcon("round-thermostat", "Round thermostat"),
    CatalogIcon("radiator-valve", "Radiator valve"),
    CatalogIcon("din-relay", "DIN relay"),
    CatalogIcon("smart-meter", "Smart meter"),
    CatalogIcon("nfc-tag", "NFC tag"),
    CatalogIcon("ir-blaster", "IR blaster"),
    CatalogIcon("dual-relay", "Dual relay"),
    CatalogIcon("fan-switch", "Fan switch"),
    CatalogIcon("temp-sensor", "Temperature sensor"),
    CatalogIcon("humidity-sensor", "Humidity sensor"),
    CatalogIcon("pir-sensor", "PIR sensor"),
    CatalogIcon("air-quality", "Air quality"),
    CatalogIcon("co2-monitor", "CO2 monitor"),
    CatalogIcon("sound-sensor", "Sound sensor"),
    CatalogIcon("soil-sensor", "Soil sensor"),
    CatalogIcon("rain-gauge", "Rain gauge"),
    CatalogIcon("anemometer", "Anemometer"),
    CatalogIcon("weather-station", "Weather station"),
    CatalogIcon("flood-sensor", "Flood sensor"),
    CatalogIcon("gas-sensor", "Gas sensor"),
    CatalogIcon("vibration-sensor", "Vibration sensor"),
    CatalogIcon("radar-sensor", "Radar sensor"),
    CatalogIcon("beam-sensor", "Beam sensor"),
    CatalogIcon("power-clamp", "Power clamp"),
    CatalogIcon("water-meter", "Water meter"),
    CatalogIcon("gas-meter", "Gas meter"),
    CatalogIcon("barometer", "Barometer"),
    CatalogIcon("bed-sensor", "Bed sensor"),
    CatalogIcon("split-ac", "Split AC"),
    CatalogIcon("cassette-ac", "Cassette AC"),
    CatalogIcon("portable-ac", "Portable AC"),
    CatalogIcon("wall-convector", "Wall convector"),
    CatalogIcon("towel-dryer", "Towel dryer"),
    CatalogIcon("floor-heating", "Floor heating"),
    CatalogIcon("ventilation-unit", "Ventilation unit"),
    CatalogIcon("air-damper", "Air damper"),
    CatalogIcon("air-filter", "Air filter"),
    CatalogIcon("pellet-stove", "Pellet stove"),
    CatalogIcon("patio-heater", "Patio heater"),
    CatalogIcon("hot-tub", "Hot tub"),
    CatalogIcon("tower-fan", "Tower fan"),
    CatalogIcon("mini-fan", "Mini fan"),
    CatalogIcon("oil-radiator", "Oil radiator"),
    CatalogIcon("radiant-panel", "Radiant panel"),
    CatalogIcon("roller-blind", "Roller blind"),
    CatalogIcon("roman-shade", "Roman shade"),
    CatalogIcon("vertical-blind", "Vertical blind"),
    CatalogIcon("blackout-curtain", "Blackout curtain"),
    CatalogIcon("roof-window", "Roof window"),
    CatalogIcon("barrier-gate", "Barrier gate"),
    CatalogIcon("swing-gate", "Swing gate"),
    CatalogIcon("roller-shutter", "Roller shutter"),
    CatalogIcon("fly-screen", "Fly screen"),
    CatalogIcon("honeycomb-shade", "Honeycomb shade"),
    CatalogIcon("deadbolt", "Deadbolt"),
    CatalogIcon("door-handle", "Door handle"),
    CatalogIcon("door-knob", "Door knob"),
    CatalogIcon("door-chain", "Door chain"),
    CatalogIcon("door-viewer", "Door viewer"),
    CatalogIcon("card-reader", "Card reader"),
    CatalogIcon("gate-opener", "Gate opener"),
    CatalogIcon("door-hinge", "Door hinge"),
    CatalogIcon("door-stop", "Door stop"),
    CatalogIcon("mail-slot", "Mail slot"),
    CatalogIcon("bullet-camera", "Bullet camera"),
    CatalogIcon("ptz-camera", "PTZ camera"),
    CatalogIcon("floodlight-cam", "Floodlight camera"),
    CatalogIcon("trail-camera", "Trail camera"),
    CatalogIcon("baby-monitor", "Baby monitor"),
    CatalogIcon("alarm-panel", "Alarm panel"),
    CatalogIcon("key-fob", "Key fob"),
    CatalogIcon("window-alarm", "Window alarm"),
    CatalogIcon("siren-strobe", "Siren strobe"),
    CatalogIcon("panic-pendant", "Panic pendant"),
    CatalogIcon("solar-inverter", "Solar inverter"),
    CatalogIcon("breaker-panel", "Breaker panel"),
    CatalogIcon("generator", "Generator"),
    CatalogIcon("ups", "UPS"),
    CatalogIcon("home-battery", "Home battery"),
    CatalogIcon("electric-car", "Electric car"),
    CatalogIcon("charging-cable", "Charging cable"),
    CatalogIcon("e-bike", "E-bike"),
    CatalogIcon("e-scooter", "E-scooter"),
    CatalogIcon("pool-pump", "Pool pump"),
    CatalogIcon("pressure-tank", "Pressure tank"),
    CatalogIcon("sump-pump", "Sump pump"),
    CatalogIcon("pet-feeder", "Pet feeder"),
    CatalogIcon("pet-fountain", "Pet fountain"),
    CatalogIcon("litter-box", "Litter box"),
    CatalogIcon("mower-dock", "Mower dock"),
    CatalogIcon("vacuum-dock", "Vacuum dock"),
    CatalogIcon("window-robot", "Window robot"),
    CatalogIcon("smoker", "Smoker"),
    CatalogIcon("pizza-oven", "Pizza oven"),
    CatalogIcon("outdoor-fridge", "Outdoor fridge"),
    CatalogIcon("ice-maker", "Ice maker"),
    CatalogIcon("wine-cooler", "Wine cooler"),
    CatalogIcon("sous-vide", "Sous vide"),
    CatalogIcon("air-fryer", "Air fryer"),
    CatalogIcon("stand-mixer", "Stand mixer"),
    CatalogIcon("drip-irrigation", "Drip irrigation"),
    CatalogIcon("irrigation-valve", "Irrigation valve"),
    CatalogIcon("rain-barrel", "Rain barrel"),
    CatalogIcon("compost-bin", "Compost bin"),
    CatalogIcon("gazebo", "Gazebo"),
    CatalogIcon("fire-pit", "Fire pit"),
    CatalogIcon("hammock", "Hammock"),
    CatalogIcon("porch-swing", "Porch swing"),
    CatalogIcon("trampoline", "Trampoline"),
    CatalogIcon("dog-house", "Dog house"),
    CatalogIcon("chicken-coop", "Chicken coop"),
    CatalogIcon("beehive", "Beehive"),
    CatalogIcon("smart-hub", "Smart hub"),
    CatalogIcon("light-bridge", "Light bridge"),
    CatalogIcon("ceiling-ap", "Ceiling AP"),
    CatalogIcon("mesh-node", "Mesh node"),
    CatalogIcon("wifi-extender", "Wi-Fi extender"),
    CatalogIcon("network-switch", "Network switch"),
    CatalogIcon("server-rack", "Server rack"),
    CatalogIcon("nas", "NAS"),
    CatalogIcon("modem", "Modem"),
    CatalogIcon("rj45-plug", "RJ45 plug"),
    CatalogIcon("voice-puck", "Voice puck"),
    CatalogIcon("voice-display", "Voice display"),
    CatalogIcon("voice-speaker", "Voice speaker"),
    CatalogIcon("smart-dial", "Smart dial"),
    CatalogIcon("curtain-motor", "Curtain motor"),
    CatalogIcon("blind-motor", "Blind motor"),
    CatalogIcon("window-motor", "Window motor"),
    CatalogIcon("garage-opener", "Garage opener"),
    CatalogIcon("french-fridge", "French-door fridge"),
    CatalogIcon("induction-hob", "Induction hob"),
)

_BY_ID: dict[str, CatalogIcon] = {icon.icon_id: icon for icon in ICONS}

# What a card means by "no icon chosen": the client draws whatever its domain
# suggests. It is the empty string rather than a name, so that "automatic" can
# never collide with a catalog identifier.
ICON_AUTOMATIC = ""


def icon_ids() -> tuple[str, ...]:
    """Return every published identifier, in catalog order."""
    return tuple(icon.icon_id for icon in ICONS)


def find_icon(value: Any) -> CatalogIcon | None:
    """Return the catalog row a request names, or None for anything else.

    This is the only way in. A value that is not a string, does not match the
    identifier pattern, or is not in the catalog answers None, and a caller
    that has None has no filename to build.
    """
    if not isinstance(value, str):
        return None
    if ICON_ID_PATTERN.match(value) is None:
        return None
    return _BY_ID.get(value)


def is_known_icon(value: Any) -> bool:
    """Return whether the catalog publishes this identifier."""
    return find_icon(value) is not None


def normalize_icon_id(value: Any) -> str:
    """Return a stored icon identifier, or "" for automatic.

    Anything the catalog does not publish reads as automatic rather than as an
    error, because this is also what reads values off disk: an icon removed
    from the catalog must leave its card drawing the domain's own artwork, not
    stop the panel from loading.
    """
    icon = find_icon(str(value).strip() if value is not None else "")
    return icon.icon_id if icon is not None else ICON_AUTOMATIC


def is_supported_size(value: Any) -> bool:
    """Return whether a client may ask for this pixel size."""
    if isinstance(value, bool):
        return False
    try:
        size = int(value)
    except (TypeError, ValueError):
        return False
    return size in SUPPORTED_SIZES


def catalog_revision() -> int:
    """Return a fingerprint of the published catalog.

    A client keeps the last value it saw and skips the download when it has
    not moved. It is a checksum rather than a counter for the same reason the
    config sensor's `revision` is: it survives a restart with no stored state,
    and reverting a change restores the previous value.
    """
    canonical = "\n".join(
        f"{icon.icon_id}\t{icon.label}" for icon in ICONS
    )
    return zlib.crc32(canonical.encode("utf-8"))


def catalog_payload() -> dict[str, Any]:
    """Return the catalog document a client downloads.

    It carries no image data at all, by design: this is the document a device
    may fetch on a schedule, and the pictures are separate requests it makes
    only for the icons it actually draws.
    """
    return {
        "revision": catalog_revision(),
        "sizes": list(SUPPORTED_SIZES),
        "esp32_bytes": ESP32_VARIANT_BYTES,
        "icons": [icon.as_payload() for icon in ICONS],
    }


def esp32_header(size: int) -> bytes:
    """Return the eight bytes that head a pre-rendered ESP32 variant.

    The size travels with the pixels so that a client can prove it received
    the variant it asked for. Without it a truncated or mis-routed response
    would be indistinguishable from a correct one of another size, and the
    firmware would point LVGL at a buffer of the wrong shape.
    """
    return ESP32_MAGIC + bytes(
        (
            size & 0xFF,
            (size >> 8) & 0xFF,
            size & 0xFF,
            (size >> 8) & 0xFF,
        )
    )


def esp32_variant_bytes(size: int) -> int:
    """Return the exact length of one pre-rendered variant, header included."""
    return ESP32_HEADER_BYTES + size * size * ESP32_BYTES_PER_PIXEL
