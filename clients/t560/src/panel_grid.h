#ifndef T560_PANEL_GRID_H
#define T560_PANEL_GRID_H

#include "app_config.h"

/* The arrangement of room-control cards on the panel's room page.
 *
 * The registry that arrives from Home Assistant says *what* this panel can
 * control; this says *where* each of those things is drawn and how large it
 * is. The two are deliberately separate: Home Assistant owns the registry and
 * has no opinion about the grid, and the grid is edited on the tablet itself,
 * in the small web page the panel serves.
 *
 * A card is keyed on `rid`, never on an entity ID. A Home Assistant entity ID
 * is renamed by the user at will and a grid keyed on one would scatter the
 * next time somebody tidied their entity IDs.
 *
 * Positions and sizes are in **cells**, never in pixels. How large a cell is
 * follows from the work area the room page happens to have, so the same file
 * lays out correctly whatever the page is given.
 */

/* The grid a first run writes, and the only one the editor offers. It is not
 * a limit on what can be read: a file naming another size is honoured, so a
 * layout is not silently reshaped by a build that disagrees with it. */
enum {
    PANEL_GRID_COLUMNS = 10,
    PANEL_GRID_ROWS = 14,
    /* The format version written into the file. A file naming another one is
     * refused rather than guessed at: reading a format this build does not
     * know would quietly move somebody's cards. */
    PANEL_GRID_VERSION = 1,
    /* Bounds on a grid this build will read at all. They exist because the
     * file can be written by hand and by a browser, so neither the cell count
     * nor the card count may be taken on trust. */
    PANEL_GRID_MIN_SIZE = 1,
    PANEL_GRID_MAX_SIZE = 64,
    PANEL_GRID_MAX_CARDS = 256
};

/* One card. `icon` and `color` are the user's overrides and are NULL when
 * they never chose one, in which case the card is drawn from its domain. */
typedef struct {
    guint x;
    guint y;
    guint width;
    guint height;
    gchar *rid;
    gchar *icon;
    gchar *color;
} PanelCard;

typedef struct {
    guint columns;
    guint rows;
    /* PanelCard*, owned, in the order they are drawn and edited. */
    GPtrArray *cards;
} PanelGrid;

PanelGrid *panel_grid_new(guint columns, guint rows);
void panel_grid_free(PanelGrid *grid);
void panel_card_free(PanelCard *card);

/* Reads one layout document.
 *
 * Geometry is validated here and identity is not: a card that does not fit
 * the grid, overlaps a card already placed, or has no usable rid is dropped,
 * and a card naming a `rid` the registry does not carry is **kept**. The
 * registry is a live payload that is empty while Home Assistant is
 * unreachable, and dropping cards against it would let one bad poll erase a
 * layout the next save then writes back.
 *
 * Returns NULL and sets `error_message` when the document itself is unusable:
 * not JSON, not an object, empty, or a format version this build does not
 * know. `dropped` is optional and receives how many cards were discarded. */
PanelGrid *panel_grid_parse(const gchar *data, gssize length, guint *dropped,
                            gchar **error_message);
gchar *panel_grid_to_json(const PanelGrid *grid);

/* Whether this card may be placed: inside the grid, at least one cell in each
 * direction, and clear of every card already in `grid`. */
gboolean panel_grid_can_place(const PanelGrid *grid, const PanelCard *card);

/* Every registry element as a 2x2 card, in registry order, left to right and
 * top to bottom. This is what a panel draws before anybody has opened the
 * editor, so that it is useful the moment it is configured in Home Assistant
 * rather than after a second, undiscoverable step. */
PanelGrid *panel_grid_default(const PanelLayout *layout);

/* The layout file, which lives next to config.ini rather than in the cache:
 * the cache is what Home Assistant last said and is safe to lose, and this is
 * the user's own arrangement and is not. */
gchar *panel_grid_path(void);
/* Reads the file, falling back to a default grid built from the registry when
 * there is none or it cannot be read. Never returns NULL. */
PanelGrid *panel_grid_load(const PanelLayout *layout);
gboolean panel_grid_save(const PanelGrid *grid, gchar **error_message);

#endif
