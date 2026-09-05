"""The unbounded entity registry a panel draws its room controls from.

This replaces the fixed room slots for panels. A slot was a numbered position
backed by a proxy entity, and there were four to six of them; a registry
element is an ordinary record with an identity of its own, there is no upper
bound but the client profile's, and it names the real entity rather than a
proxy. See docs/CONTRACT.md, **Registry entries**.

Three ideas carry the whole module:

* **`rid` is the identity, not the entity ID.** A Home Assistant entity ID is
  renamed by the user at will, and a device that lets somebody arrange its own
  grid must key that layout on something that does not move underneath it. A
  `rid` is minted once, never changes while the element exists, and is never
  handed out again after one is deleted — which is what `retired` is for.
* **The entity registry ID is what survives a rename.** `rid` keeps the
  element's identity; `registry_id` keeps the *target's*, so that renaming
  `light.desk_lamp` to `light.study_lamp` moves the element with it instead of
  leaving it pointing at nothing.
* **Groups are presentation, not storage.** An element carries its domain and
  the group is derived from it, so adding a group later cannot invalidate
  anything already stored.

An element also carries the two things a person may say about how it is drawn:
the `name` on its tile and the `icon` above it. Both are stored here, keyed by
`rid`, rather than in the layout document each device keeps, because both are
facts about the element and not about where somebody dragged it: a house with
two panels names a lamp once, and a device that is wiped gets the name and the
icon back with the registry rather than out of a file it no longer has.

This module deliberately has no Home Assistant imports, so all of that can be
tested without a Home Assistant runtime. Resolving a target's capabilities and
its current entity ID needs `hass` and lives in `slots.py`.
"""

from __future__ import annotations

from collections.abc import Callable, Container, Iterable, Mapping
from dataclasses import dataclass, replace
import secrets
from typing import Any
import unicodedata

# A rid is eight lowercase hex characters, which is what the contract
# publishes and what a client stores its grid layout against.
RID_LENGTH = 8
_RID_BITS = RID_LENGTH * 4

# Keys of one stored registry record. They appear in config entries on disk
# and, except `registry_id`, in the client contract, so they may not be
# renamed casually.
REGISTRY_KEY_RID = "rid"
REGISTRY_KEY_ENTITY = "entity"
REGISTRY_KEY_DOMAIN = "domain"
REGISTRY_KEY_NAME = "name"
REGISTRY_KEY_CONTROLS = "controls"
REGISTRY_KEY_MIN_KELVIN = "min_kelvin"
REGISTRY_KEY_MAX_KELVIN = "max_kelvin"
REGISTRY_KEY_MIN_TEMP = "min_temp"
REGISTRY_KEY_MAX_TEMP = "max_temp"
REGISTRY_KEY_TEMP_STEP = "target_temp_step"
REGISTRY_KEY_ICON = "icon"
# Not part of the contract: the Home Assistant entity registry row ID of the
# target. It never reaches a client, and it is what makes an element follow
# its entity through a rename.
REGISTRY_KEY_REGISTRY_ID = "registry_id"


@dataclass(frozen=True, slots=True)
class RegistryGroup:
    """One heading in the registry form, and the domain it collects."""

    slug: str
    domain: str


# In payload order. Lights, switches, climate and covers draw controls; weather
# and sensors are carried with an empty control list and drawn as readings
# rather than controls — see docs/CONTRACT.md, Weather blocks and Sensor
# blocks. A client ignores an element whose domain it cannot draw, so a group
# added here cannot break a client already in the field.
GROUPS: tuple[RegistryGroup, ...] = (
    RegistryGroup("lights", "light"),
    RegistryGroup("switches", "switch"),
    RegistryGroup("climate", "climate"),
    RegistryGroup("covers", "cover"),
    RegistryGroup("weather", "weather"),
    RegistryGroup("sensors", "sensor"),
)

# Groups that were offered once and are not any more. Their elements are
# retired the next time a panel is saved: nothing can edit them, and one that
# stayed would keep a place in the registry that nobody could reach.
# `media_player` was dropped because a panel already has a media player of its
# own — its source — chosen on the same page and drawn by the player card.
RETIRED_GROUP_DOMAINS: tuple[str, ...] = ("media_player",)

# How long a display name may be, in characters rather than bytes. It is a
# memory bound and not a taste one: the paired ESP32 holds the whole registry
# in RAM and reads it out of a fixed response buffer, so an unbounded name is
# an unbounded payload. Characters, because the name is UTF-8 and a limit in
# bytes would let a Latin name be twice as long as a Cyrillic one for no
# reason a person could see.
MAX_NAME_LENGTH = 64

# Why a name can be refused. They are returned rather than raised so that the
# endpoint keeps control of its own answers, exactly as the ownership check
# does in `status.py`.
NAME_OK = ""
NAME_TOO_LONG = "name_too_long"
NAME_UNPRINTABLE = "name_unprintable"

GROUP_DOMAINS: tuple[str, ...] = tuple(group.domain for group in GROUPS)
_GROUP_ORDER: dict[str, int] = {
    group.domain: index for index, group in enumerate(GROUPS)
}


def group_by_slug(slug: str) -> RegistryGroup | None:
    """Return the group a form step belongs to, or None for an unknown one."""
    for group in GROUPS:
        if group.slug == slug:
            return group
    return None


@dataclass(frozen=True, slots=True)
class RegistryEntry:
    """One element of a panel's entity registry, as stored."""

    rid: str
    target_entity_id: str
    domain: str
    name: str = ""
    registry_id: str = ""
    controls: tuple[str, ...] = ()
    min_kelvin: int | None = None
    max_kelvin: int | None = None
    # The setpoint bounds of a thermostat, in whatever unit the entity itself
    # reports. They are the climate card's `min_kelvin` and `max_kelvin`, and
    # like those they are present only when the matching control is.
    min_temp: float | None = None
    max_temp: float | None = None
    target_temp_step: float | None = None
    # A catalog identifier, or "" for automatic. It is a name and never a
    # position: `icon_catalog.ICONS` may be reordered, added to or shortened
    # without changing what any stored element points at.
    #
    # It is stored here as an opaque string on purpose. Whether the catalog
    # still publishes it is `icon_catalog`'s question, asked once on the way
    # in — `panel_card.py` refuses an identifier that is not published — and
    # again on the way out, where `slots.py` turns one the catalog has since
    # dropped back into automatic. Neither belongs in a module that has to
    # stay loadable with no imports at all.
    icon: str = ""

    def as_stored(self) -> dict[str, Any]:
        """Return the config-entry representation of this element."""
        stored: dict[str, Any] = {
            REGISTRY_KEY_RID: self.rid,
            REGISTRY_KEY_ENTITY: self.target_entity_id,
            REGISTRY_KEY_DOMAIN: self.domain,
            REGISTRY_KEY_NAME: self.name,
            REGISTRY_KEY_CONTROLS: list(self.controls),
        }
        if self.registry_id:
            stored[REGISTRY_KEY_REGISTRY_ID] = self.registry_id
        if self.min_kelvin is not None:
            stored[REGISTRY_KEY_MIN_KELVIN] = self.min_kelvin
        if self.max_kelvin is not None:
            stored[REGISTRY_KEY_MAX_KELVIN] = self.max_kelvin
        if self.min_temp is not None:
            stored[REGISTRY_KEY_MIN_TEMP] = self.min_temp
        if self.max_temp is not None:
            stored[REGISTRY_KEY_MAX_TEMP] = self.max_temp
        if self.target_temp_step is not None:
            stored[REGISTRY_KEY_TEMP_STEP] = self.target_temp_step
        # Written only when one was chosen, so an entry saved before icons
        # existed and one whose icon is automatic are the same record on disk.
        if self.icon:
            stored[REGISTRY_KEY_ICON] = self.icon
        return stored

    @classmethod
    def from_stored(cls, stored: Mapping[str, Any]) -> RegistryEntry | None:
        """Read one stored element, ignoring an incomplete record."""
        rid = str(stored.get(REGISTRY_KEY_RID) or "")
        entity_id = str(stored.get(REGISTRY_KEY_ENTITY) or "")
        if not rid or not entity_id:
            return None
        domain = str(stored.get(REGISTRY_KEY_DOMAIN) or "") or entity_id.split(
            "."
        )[0]
        return cls(
            rid=rid,
            target_entity_id=entity_id,
            domain=domain,
            name=str(stored.get(REGISTRY_KEY_NAME) or ""),
            registry_id=str(stored.get(REGISTRY_KEY_REGISTRY_ID) or ""),
            controls=tuple(stored.get(REGISTRY_KEY_CONTROLS) or ()),
            min_kelvin=stored.get(REGISTRY_KEY_MIN_KELVIN),
            max_kelvin=stored.get(REGISTRY_KEY_MAX_KELVIN),
            min_temp=stored.get(REGISTRY_KEY_MIN_TEMP),
            max_temp=stored.get(REGISTRY_KEY_MAX_TEMP),
            target_temp_step=stored.get(REGISTRY_KEY_TEMP_STEP),
            icon=str(stored.get(REGISTRY_KEY_ICON) or "").strip(),
        )


def stored_entries(
    source: Mapping[str, Any],
    key: str,
) -> list[RegistryEntry]:
    """Read every valid registry element from an entry mapping."""
    raw = source.get(key) or ()
    entries = [
        entry
        for record in raw
        if isinstance(record, Mapping)
        and (entry := RegistryEntry.from_stored(record)) is not None
    ]
    return sort_entries(_without_duplicate_rids(entries))


def stored_retired_rids(source: Mapping[str, Any], key: str) -> list[str]:
    """Read the rids of elements that have been deleted.

    They are kept so that a rid is never handed out twice: a device stores its
    grid layout against them, and a reused rid would silently move a tile to
    whatever entity took the old one's place.
    """
    return [str(rid) for rid in (source.get(key) or ()) if rid]


def sort_entries(entries: Iterable[RegistryEntry]) -> list[RegistryEntry]:
    """Return the elements in payload order: by group, then as added.

    An unknown domain sorts after every known group rather than being dropped,
    so a registry written by a newer build stays readable by an older one.
    """
    return [
        entry
        for _, _, entry in sorted(
            (
                (_GROUP_ORDER.get(entry.domain, len(GROUPS)), position, entry)
                for position, entry in enumerate(entries)
            ),
            key=lambda item: (item[0], item[1]),
        )
    ]


def new_rid(
    taken: Container[str],
    *,
    _random: Callable[[int], int] = secrets.randbelow,
) -> str:
    """Mint a rid that has never been used by this client.

    `taken` must cover the live elements *and* the retired ones. The draw is
    from the full 32-bit space rather than a counter so that two rids carry no
    relationship a client might be tempted to read something into.
    """
    while True:
        candidate = f"{_random(1 << _RID_BITS):0{RID_LENGTH}x}"
        if candidate not in taken:
            return candidate


def group_selection(
    entries: Iterable[RegistryEntry],
    domain: str,
) -> list[str]:
    """Return the entity IDs currently in one group, in their stored order."""
    return [
        entry.target_entity_id for entry in entries if entry.domain == domain
    ]


def replace_group(
    entries: Iterable[RegistryEntry],
    domain: str,
    selected: Iterable[str],
    *,
    retired: Iterable[str] = (),
    rid_source: Callable[[Container[str]], str] = new_rid,
) -> tuple[list[RegistryEntry], list[str]]:
    """Rewrite one group from the entity IDs a form submitted.

    Returns the whole registry and the rids that were retired by this edit.
    An entity that is still selected keeps the element it already had, `rid`
    and all; one that is no longer selected has its element deleted and its
    rid retired; one that is newly selected gets a fresh element.
    """
    existing = list(entries)
    kept_by_entity: dict[str, RegistryEntry] = {
        entry.target_entity_id: entry
        for entry in existing
        if entry.domain == domain
    }

    taken: set[str] = {entry.rid for entry in existing} | set(retired)
    rebuilt: list[RegistryEntry] = []
    survivors: set[str] = set()
    for entity_id in selected:
        entity_id = str(entity_id)
        if not entity_id or entity_id in survivors:
            continue
        survivors.add(entity_id)
        if (kept := kept_by_entity.get(entity_id)) is not None:
            rebuilt.append(kept)
            continue
        rid = rid_source(taken)
        taken.add(rid)
        rebuilt.append(
            RegistryEntry(
                rid=rid,
                target_entity_id=entity_id,
                domain=domain,
            )
        )

    newly_retired = [
        entry.rid
        for entity_id, entry in kept_by_entity.items()
        if entity_id not in survivors
    ]
    others = [entry for entry in existing if entry.domain != domain]
    return sort_entries(others + rebuilt), newly_retired


def find_entry(
    entries: Iterable[RegistryEntry],
    rid: str,
) -> RegistryEntry | None:
    """Return the element with this rid, or None when there is none."""
    for entry in entries:
        if entry.rid == rid:
            return entry
    return None


def normalize_name(value: Any) -> tuple[str, str]:
    """Return a display name ready to store, and why it was refused.

    The rules, and why each one is here:

    * leading and trailing whitespace is **trimmed**, so a name that is only
      spaces is the same as no name at all. Somebody who clears the field by
      selecting all and pressing space means "clear it";
    * an empty result means **use the Home Assistant entity's own name**. That
      is the one value with a meaning of its own, and it is what makes the
      field clearable without a second control;
    * every script is accepted. Cyrillic, Greek, CJK and emoji are ordinary
      names, and the payload has been UTF-8 since the registry existed;
    * control characters are **refused**, not stripped. A newline in a tile
      label is somebody pasting the wrong thing, and quietly keeping half of
      what they pasted is worse than telling them;
    * the length is bounded because the paired ESP32 keeps the whole registry
      in RAM and reads it out of a fixed response buffer. See
      `MAX_NAME_LENGTH`.

    Length is measured after Unicode normalization to NFC, so that a name
    typed with combining accents and the same name typed with precomposed
    ones are the same length as well as the same name.
    """
    if value is None:
        return "", NAME_OK
    if not isinstance(value, str):
        return "", NAME_UNPRINTABLE
    name = unicodedata.normalize("NFC", value).strip()
    if not name:
        return "", NAME_OK
    if any(unicodedata.category(character) == "Cc" for character in name):
        return "", NAME_UNPRINTABLE
    if len(name) > MAX_NAME_LENGTH:
        return "", NAME_TOO_LONG
    return name, NAME_OK


def apply_card_appearance(
    entries: Iterable[RegistryEntry],
    rid: str,
    *,
    name: str | None = None,
    icon: str | None = None,
) -> tuple[list[RegistryEntry], bool]:
    """Set the name and icon of one element, and say whether anything moved.

    Both arguments are optional and `None` means "leave this one alone", so
    the endpoint can carry either half of the form without the other half
    having to send a value it did not ask about.

    An unknown `rid` changes nothing: the caller establishes that it is known
    with `find_entry` first and answers 404 itself, which is what keeps the
    editor route from becoming a way to add entities to a panel.
    """
    original = list(entries)
    updated: list[RegistryEntry] = []
    found = False
    changed = False
    for entry in original:
        if entry.rid != rid:
            updated.append(entry)
            continue
        found = True
        replacement = entry
        if name is not None:
            replacement = replace(replacement, name=name)
        if icon is not None:
            replacement = replace(replacement, icon=icon.strip())
        changed = replacement != entry
        updated.append(replacement)
    if not found:
        return original, False
    return updated, changed


def apply_names(
    entries: Iterable[RegistryEntry],
    names: Mapping[str, str],
) -> list[RegistryEntry]:
    """Apply labels to elements, keyed by rid.

    An element the mapping does not mention is left alone, so a caller that
    knows about some of the registry cannot clear the labels of the rest.

    Nothing in the flows calls this today: the settings page stopped asking
    for a label, and a tile is named as Home Assistant names its entity. A
    stored label is still read, still sent and still preferred over that name,
    so this is what writes one when something asks for labels again.
    """
    updated: list[RegistryEntry] = []
    for entry in entries:
        if entry.rid in names:
            updated.append(
                replace(entry, name=str(names[entry.rid] or "").strip())
            )
        else:
            updated.append(entry)
    return updated


def resolve_entity_ids(
    entries: Iterable[RegistryEntry],
    lookup: Callable[[RegistryEntry], tuple[str, str]],
) -> list[RegistryEntry]:
    """Follow every element's target through a Home Assistant rename.

    `lookup` answers with the target's current entity ID and its entity
    registry row ID. Home Assistant keeps that row ID across a rename, so an
    element that has one follows the entity; one that has none — an element
    whose target is not in the entity registry at all — keeps the entity ID it
    was given and simply goes unavailable if the entity really is gone.
    """
    resolved: list[RegistryEntry] = []
    for entry in entries:
        entity_id, registry_id = lookup(entry)
        if not entity_id:
            resolved.append(entry)
            continue
        if (
            entity_id == entry.target_entity_id
            and registry_id == entry.registry_id
        ):
            resolved.append(entry)
            continue
        resolved.append(
            replace(
                entry,
                target_entity_id=entity_id,
                domain=entity_id.split(".")[0],
                registry_id=registry_id,
            )
        )
    return resolved


def _without_duplicate_rids(
    entries: Iterable[RegistryEntry],
) -> list[RegistryEntry]:
    """Drop any repeated rid, keeping the first.

    Two elements sharing a rid would give a client two tiles it cannot tell
    apart. It cannot happen through the flows; this is what keeps a hand-edited
    or half-written entry from producing one.
    """
    seen: set[str] = set()
    unique: list[RegistryEntry] = []
    for entry in entries:
        if entry.rid in seen:
            continue
        seen.add(entry.rid)
        unique.append(entry)
    return unique
