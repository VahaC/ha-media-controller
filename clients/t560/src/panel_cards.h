#ifndef T560_PANEL_CARDS_H
#define T560_PANEL_CARDS_H

#include <glib.h>

/* What a room card may be called, and what it may be drawn with.
 *
 * Both answers belong to Home Assistant. The Media Controller integration
 * keeps a display name and an icon identifier against every registry element,
 * the panel reads them out of the config payload like everything else, and the
 * editor asks the panel to change them. This module is the panel's half of
 * that: the rules a name has to pass and the catalog of pictures, held where
 * the editor can read it without a Home Assistant call of its own.
 *
 * Two ideas carry it, and both are the same ones the integration is built on:
 *
 * * **an identifier is a key, never a path.** A catalog row is looked up, and
 *   a value that is not a row is nothing. Nothing here builds a filename, a
 *   URL or a resource path out of something a caller said;
 * * **the catalog is not the order.** A card stores an identifier. Adding to,
 *   removing from or reordering the catalog cannot change what a card already
 *   points at.
 *
 * There are no Home Assistant imports here and no GTK ones, so all of it can
 * be tested on its own. Fetching the catalog and the pictures needs the HTTP
 * client and lives in `application.c`.
 */

typedef struct _PanelCards PanelCards;

/* How long a display name may be, in characters and not in bytes. It is the
 * integration's own limit, checked here as well so that the editor is told at
 * once rather than after a round trip. Characters, because the name is UTF-8
 * and a limit in bytes would let a Latin name be twice as long as a Cyrillic
 * one for no reason a person could see. */
#define PANEL_CARD_NAME_MAX_CHARS 64

/* Why a name was refused, for the message the editor shows. */
typedef enum {
    PANEL_CARD_NAME_OK = 0,
    PANEL_CARD_NAME_TOO_LONG,
    PANEL_CARD_NAME_UNPRINTABLE
} PanelCardNameResult;

/* Trims a display name and says whether it may be stored.
 *
 * The rules, and why each one is here:
 *
 * * whitespace at either end is dropped, so a field cleared by typing a space
 *   is the same as one that was emptied;
 * * an empty result means **use the Home Assistant entity's own name**. That
 *   is the one value with a meaning of its own, and it is what makes the
 *   field clearable without a second control;
 * * every script is accepted. Cyrillic, Greek, CJK and emoji are ordinary
 *   names and the payload has been UTF-8 since the registry existed;
 * * control characters are refused rather than stripped. A newline in a tile
 *   label is somebody pasting the wrong thing, and quietly keeping half of
 *   what they pasted is worse than telling them;
 * * the length is bounded, because the paired ESP32 panel across the house
 *   reads the same registry out of a fixed response buffer.
 *
 * `normalized` receives a newly allocated string on OK and NULL otherwise. */
PanelCardNameResult panel_card_name_normalize(const gchar *value,
                                              gchar **normalized);
/* The message the editor shows for a refusal, or NULL for OK. */
const gchar *panel_card_name_error(PanelCardNameResult result);

/* Whether this is something the catalog could plausibly publish: lowercase,
 * digits and hyphens, bounded, not starting with a hyphen. It is checked
 * before an identifier is stored, asked for, or put on the wire, so nothing
 * that reaches a URL came unexamined off one. */
gboolean panel_card_icon_id_is_sane(const gchar *id);

PanelCards *panel_cards_new(void);
void panel_cards_free(PanelCards *cards);

/* Reads one `/api/media_controller/icons` document. Returns TRUE when the
 * catalog actually changed, which is what tells the caller to stop asking for
 * a while. The document carries no image data at all: the pictures are
 * separate requests, made only for the identifiers that are wanted. */
gboolean panel_cards_set_catalog(PanelCards *cards, const gchar *document,
                                 gssize length);
guint panel_cards_catalog_size(PanelCards *cards);
const gchar *panel_cards_catalog_id(PanelCards *cards, guint index);
const gchar *panel_cards_catalog_label(PanelCards *cards, guint index);
gboolean panel_cards_publishes(PanelCards *cards, const gchar *id);

/* One picture, as the bytes Home Assistant served, or NULL when it has not
 * arrived. The cache is keyed on the identifier, so a page of a hundred cards
 * naming three pictures holds three of them. */
GBytes *panel_cards_image(PanelCards *cards, const gchar *id);
/* Stores one downloaded picture. An identifier the catalog does not publish
 * is refused, so nothing can be planted here by asking for it. */
void panel_cards_store_image(PanelCards *cards, const gchar *id,
                             GBytes *image);
/* Records that a picture did not arrive, so that it is left alone for a while
 * instead of asked for again on every tick. */
void panel_cards_mark_missing(PanelCards *cards, const gchar *id);
/* The next identifier worth asking for, or NULL when there is nothing to
 * fetch. One at a time, in catalog order, skipping what is already held and
 * what failed recently. */
const gchar *panel_cards_next_wanted(PanelCards *cards);
gboolean panel_cards_needs_image(PanelCards *cards, const gchar *id);

/* How the last card edit ended, for the editor to watch. The write reaches
 * Home Assistant asynchronously, so it cannot be answered inside the request
 * that asked for it — the same shape the restore already has. */
typedef enum {
    PANEL_CARD_WRITE_IDLE = 0,
    PANEL_CARD_WRITE_PENDING,
    PANEL_CARD_WRITE_OK,
    PANEL_CARD_WRITE_FAILED
} PanelCardWriteState;

void panel_cards_write_started(PanelCards *cards);
void panel_cards_write_finished(PanelCards *cards, gboolean ok,
                                const gchar *message);
PanelCardWriteState panel_cards_write_state(PanelCards *cards);
const gchar *panel_cards_write_message(PanelCards *cards);

#endif
