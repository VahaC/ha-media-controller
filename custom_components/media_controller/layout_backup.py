"""The rules for the copy of its own grid that a panel leaves in Home Assistant.

A T560 panel arranges its registry into a grid, and that arrangement lives on
the tablet: it is edited there, in a small web page the panel serves, and Home
Assistant has no opinion about it. What Home Assistant has is somewhere
durable to put a copy, which is the one thing the tablet cannot provide for
itself. Wiping the tablet, reinstalling the application, or replacing it loses
the file; a panel derives the same `panel_id` from the same machine, so it
finds its copy again.

Two things decide how that behaves, and both live here rather than in the view
next to them, so that they can be tested without a Home Assistant runtime — the
same reason `contract.py` is a module of its own:

* **the blob is opaque.** What is stored is the bytes the panel sent. Home
  Assistant never parses them, and no key inside them means anything here. The
  grid format belongs to the client that draws it, which may change it without
  a change to `docs/CONTRACT.md`;
* **there is a ceiling.** Storing whatever a caller sends, without a limit,
  would let one panel grow the installation's storage file for as long as it
  cared to.

The Home Assistant half — the endpoint, its ownership check, and the `Store`
this is persisted through — is in `panel_layout.py`.
"""

from __future__ import annotations

from collections.abc import Mapping

# A layout is a few hundred bytes per card and the T560 profile allows a
# hundred cards, so this is generous by roughly a factor of two.
MAX_LAYOUT_BYTES = 16 * 1024


def layout_size(layout: str) -> int:
    """Return what one stored layout costs, in bytes.

    Bytes and not characters: a layout naming Cyrillic rooms is two bytes per
    letter, and a ceiling counted in characters would be a different ceiling
    for different people.
    """
    return len(layout.encode("utf-8"))


def layout_is_too_large(layout: str) -> bool:
    """Return whether a layout is over the ceiling and must be refused."""
    return layout_size(layout) > MAX_LAYOUT_BYTES


class LayoutBackups:
    """Every panel's saved grid, by panel ID.

    One collection for the installation rather than one per panel: the whole
    point is that a layout outlives the config entry it came from, so it is
    not owned by one.
    """

    def __init__(self, stored: Mapping[str, str] | None = None) -> None:
        """Start from what was read off disk, ignoring anything unusable."""
        self._layouts: dict[str, str] = {}
        if isinstance(stored, Mapping):
            for panel_id, layout in stored.items():
                if isinstance(panel_id, str) and isinstance(layout, str):
                    self._layouts[panel_id] = layout

    def get(self, panel_id: str) -> str | None:
        """Return one panel's layout, byte for byte, or None."""
        return self._layouts.get(panel_id)

    def set(self, panel_id: str, layout: str) -> bool:
        """Store one panel's layout; return whether anything changed.

        An unchanged layout is not a write. A panel sends its copy after every
        save, and rewriting an identical storage file each time would be pure
        disk churn for a value that did not move.
        """
        if self._layouts.get(panel_id) == layout:
            return False
        self._layouts[panel_id] = layout
        return True

    def as_stored(self) -> dict[str, str]:
        """Return what belongs on disk."""
        return dict(self._layouts)
