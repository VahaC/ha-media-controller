#include "panel_cards.h"

#include "json_helpers.h"

#include <json-glib/json-glib.h>
#include <string.h>

/* How long a picture that did not arrive is left alone before it is asked for
 * again. Home Assistant being down must not turn into a request per tick, and
 * a picture that is genuinely missing must not be asked for forever. */
#define PANEL_CARD_ICON_RETRY_US (60 * G_USEC_PER_SEC)

/* Bound both the catalog and its image cache. Every accepted row must fit:
 * evicting images while walking the catalog restarts downloads forever. */
#define PANEL_CARD_CATALOG_MAX 512

typedef struct {
    gchar *id;
    gchar *label;
} CatalogRow;

typedef struct {
    /* NULL means it was asked for and did not arrive. The row is kept so that
     * the failure is remembered rather than retried on every tick. */
    GBytes *image;
    gint64 failed_at;
} CachedImage;

struct _PanelCards {
    GPtrArray *catalog;      /* CatalogRow *, in catalog order */
    guint revision;
    GHashTable *images;      /* id -> CachedImage * */
    PanelCardWriteState write_state;
    gchar *write_message;
};

static void catalog_row_free(gpointer data)
{
    CatalogRow *row = data;

    if (row == NULL)
        return;
    g_free(row->id);
    g_free(row->label);
    g_free(row);
}

static void cached_image_free(gpointer data)
{
    CachedImage *cached = data;

    if (cached == NULL)
        return;
    if (cached->image != NULL)
        g_bytes_unref(cached->image);
    g_free(cached);
}

/* ------------------------------------------------------------------ names */

PanelCardNameResult panel_card_name_normalize(const gchar *value,
                                              gchar **normalized)
{
    if (normalized != NULL)
        *normalized = NULL;
    if (value == NULL) {
        if (normalized != NULL)
            *normalized = g_strdup("");
        return PANEL_CARD_NAME_OK;
    }

    /* Trimmed before anything else, so that a field somebody cleared by
     * typing a space reads as empty and empty means "the Home Assistant
     * entity's own name". */
    gchar *trimmed = g_strdup(value);
    g_strstrip(trimmed);

    /* Refused rather than repaired. A name that is not UTF-8 did not come
     * from the editor, and guessing at what it was meant to say would store
     * something nobody typed. */
    if (!g_utf8_validate(trimmed, -1, NULL)) {
        g_free(trimmed);
        return PANEL_CARD_NAME_UNPRINTABLE;
    }

    for (const gchar *p = trimmed; *p != '\0'; p = g_utf8_next_char(p)) {
        gunichar c = g_utf8_get_char(p);
        /* Control characters only. Everything else — every script, every
         * mark, every emoji — is an ordinary name. */
        if (g_unichar_iscntrl(c)) {
            g_free(trimmed);
            return PANEL_CARD_NAME_UNPRINTABLE;
        }
    }

    if (g_utf8_strlen(trimmed, -1) > PANEL_CARD_NAME_MAX_CHARS) {
        g_free(trimmed);
        return PANEL_CARD_NAME_TOO_LONG;
    }

    if (normalized != NULL)
        *normalized = trimmed;
    else
        g_free(trimmed);
    return PANEL_CARD_NAME_OK;
}

const gchar *panel_card_name_error(PanelCardNameResult result)
{
    switch (result) {
    case PANEL_CARD_NAME_TOO_LONG:
        return "A name may be at most "
               G_STRINGIFY(PANEL_CARD_NAME_MAX_CHARS) " characters.";
    case PANEL_CARD_NAME_UNPRINTABLE:
        return "A name cannot contain control characters.";
    case PANEL_CARD_NAME_OK:
    default:
        return NULL;
    }
}

/* ------------------------------------------------------------ identifiers */

gboolean panel_card_icon_id_is_sane(const gchar *id)
{
    if (id == NULL)
        return FALSE;

    gsize length = strlen(id);
    if (length == 0 || length > 32)
        return FALSE;

    for (gsize i = 0; i < length; i++) {
        gchar c = id[i];
        if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9'))
            continue;
        /* A hyphen anywhere but first, so that "-x" is not an identifier. */
        if (c == '-' && i > 0)
            continue;
        return FALSE;
    }
    return TRUE;
}

/* --------------------------------------------------------------- lifetime */

PanelCards *panel_cards_new(void)
{
    PanelCards *cards = g_new0(PanelCards, 1);

    cards->catalog = g_ptr_array_new_with_free_func(catalog_row_free);
    cards->images = g_hash_table_new_full(g_str_hash, g_str_equal, g_free,
                                          cached_image_free);
    cards->write_state = PANEL_CARD_WRITE_IDLE;
    return cards;
}

void panel_cards_free(PanelCards *cards)
{
    if (cards == NULL)
        return;

    g_ptr_array_free(cards->catalog, TRUE);
    g_hash_table_destroy(cards->images);
    g_free(cards->write_message);
    g_free(cards);
}

/* ---------------------------------------------------------------- catalog */

gboolean panel_cards_set_catalog(PanelCards *cards, const gchar *document,
                                 gssize length)
{
    if (cards == NULL || document == NULL)
        return FALSE;

    JsonParser *parser = json_parser_new();
    GError *error = NULL;

    if (!json_parser_load_from_data(parser, document, length, &error)) {
        /* Debug rather than a warning: an unreachable or confused Home
         * Assistant is already visible on the status line, every card keeps
         * the artwork this build carries, and a line in the journal per poll
         * would bury everything else. */
        g_debug("The icon catalog was not readable: %s",
                error != NULL ? error->message : "unknown error");
        g_clear_error(&error);
        g_object_unref(parser);
        return FALSE;
    }

    JsonNode *root = json_parser_get_root(parser);
    if (root == NULL || !JSON_NODE_HOLDS_OBJECT(root)) {
        g_object_unref(parser);
        return FALSE;
    }

    JsonObject *object = json_node_get_object(root);
    gdouble value = 0.0;
    guint revision =
        json_object_number(object, "revision", &value) ? (guint)value : 0;
    JsonArray *rows = json_optional_array(object, "icons");
    if (rows == NULL) {
        g_object_unref(parser);
        return FALSE;
    }

    GPtrArray *parsed = g_ptr_array_new_with_free_func(catalog_row_free);
    guint count = json_array_get_length(rows);
    for (guint i = 0; i < count && parsed->len < PANEL_CARD_CATALOG_MAX; i++) {
        JsonNode *node = json_array_get_element(rows, i);
        if (node == NULL || !JSON_NODE_HOLDS_OBJECT(node))
            continue;

        JsonObject *entry = json_node_get_object(node);
        const gchar *id = json_object_string(entry, "id", NULL);
        if (!panel_card_icon_id_is_sane(id))
            continue;

        CatalogRow *row = g_new0(CatalogRow, 1);
        row->id = g_strdup(id);
        row->label = g_strdup(json_object_string(entry, "label", id));
        g_ptr_array_add(parsed, row);
    }
    g_object_unref(parser);

    gboolean changed = revision != cards->revision ||
                       parsed->len != cards->catalog->len;
    if (!changed) {
        for (guint i = 0; i < parsed->len; i++) {
            const CatalogRow *now = g_ptr_array_index(parsed, i);
            const CatalogRow *was = g_ptr_array_index(cards->catalog, i);
            if (g_strcmp0(now->id, was->id) != 0) {
                changed = TRUE;
                break;
            }
        }
    }
    if (!changed) {
        g_ptr_array_free(parsed, TRUE);
        return FALSE;
    }

    g_ptr_array_free(cards->catalog, TRUE);
    cards->catalog = parsed;
    cards->revision = revision;

    /* A catalog that moved is reason to try a picture that failed once more:
     * the likeliest cause of a failure is an integration that did not carry
     * the file, and the likeliest cause of a new catalog is one that now
     * does. A picture already held is kept — the identifier means the same
     * thing it did, which is the whole point of it being a name. */
    GHashTableIter iter;
    gpointer key = NULL;
    gpointer held = NULL;
    g_hash_table_iter_init(&iter, cards->images);
    while (g_hash_table_iter_next(&iter, &key, &held)) {
        CachedImage *cached = held;
        if (cached->image == NULL || !panel_cards_publishes(cards, key))
            g_hash_table_iter_remove(&iter);
    }
    return TRUE;
}

guint panel_cards_catalog_size(PanelCards *cards)
{
    return cards != NULL ? cards->catalog->len : 0;
}

const gchar *panel_cards_catalog_id(PanelCards *cards, guint index)
{
    if (cards == NULL || index >= cards->catalog->len)
        return NULL;
    return ((const CatalogRow *)g_ptr_array_index(cards->catalog, index))->id;
}

const gchar *panel_cards_catalog_label(PanelCards *cards, guint index)
{
    if (cards == NULL || index >= cards->catalog->len)
        return NULL;
    return ((const CatalogRow *)g_ptr_array_index(cards->catalog, index))
        ->label;
}

gboolean panel_cards_publishes(PanelCards *cards, const gchar *id)
{
    if (cards == NULL || id == NULL)
        return FALSE;
    for (guint i = 0; i < cards->catalog->len; i++) {
        const CatalogRow *row = g_ptr_array_index(cards->catalog, i);
        if (g_strcmp0(row->id, id) == 0)
            return TRUE;
    }
    return FALSE;
}

/* --------------------------------------------------------------- pictures */

GBytes *panel_cards_image(PanelCards *cards, const gchar *id)
{
    if (cards == NULL || id == NULL)
        return NULL;
    CachedImage *cached = g_hash_table_lookup(cards->images, id);
    return cached != NULL ? cached->image : NULL;
}

void panel_cards_store_image(PanelCards *cards, const gchar *id,
                             GBytes *image)
{
    if (cards == NULL || image == NULL)
        return;
    /* Only what the catalog publishes. Without this check the cache would be
     * a place anything could be put by asking for it. */
    if (!panel_cards_publishes(cards, id))
        return;

    /* Membership bounds the cache to PANEL_CARD_CATALOG_MAX. Catalog changes
     * remove obsolete entries, so downloading a later row keeps earlier ones. */

    CachedImage *cached = g_new0(CachedImage, 1);
    cached->image = g_bytes_ref(image);
    g_hash_table_replace(cards->images, g_strdup(id), cached);
}

void panel_cards_mark_missing(PanelCards *cards, const gchar *id)
{
    if (cards == NULL || id == NULL || !panel_cards_publishes(cards, id))
        return;

    CachedImage *cached = g_hash_table_lookup(cards->images, id);
    if (cached != NULL && cached->image != NULL)
        return;

    if (cached == NULL) {
        cached = g_new0(CachedImage, 1);
        g_hash_table_replace(cards->images, g_strdup(id), cached);
    }
    cached->failed_at = g_get_monotonic_time();
}

gboolean panel_cards_needs_image(PanelCards *cards, const gchar *id)
{
    if (!panel_cards_publishes(cards, id))
        return FALSE;
    CachedImage *cached = g_hash_table_lookup(cards->images, id);
    return cached == NULL || (cached->image == NULL &&
        g_get_monotonic_time() - cached->failed_at >= PANEL_CARD_ICON_RETRY_US);
}

const gchar *panel_cards_next_wanted(PanelCards *cards)
{
    if (cards == NULL)
        return NULL;

    gint64 now = g_get_monotonic_time();
    for (guint i = 0; i < cards->catalog->len; i++) {
        const CatalogRow *row = g_ptr_array_index(cards->catalog, i);
        CachedImage *cached = g_hash_table_lookup(cards->images, row->id);

        if (cached == NULL)
            return row->id;
        if (cached->image != NULL)
            continue;
        if (now - cached->failed_at >= PANEL_CARD_ICON_RETRY_US)
            return row->id;
    }
    return NULL;
}

/* ------------------------------------------------------------ the outcome */

void panel_cards_write_started(PanelCards *cards)
{
    if (cards == NULL)
        return;
    cards->write_state = PANEL_CARD_WRITE_PENDING;
    g_clear_pointer(&cards->write_message, g_free);
}

void panel_cards_write_finished(PanelCards *cards, gboolean ok,
                                const gchar *message)
{
    if (cards == NULL)
        return;
    cards->write_state = ok ? PANEL_CARD_WRITE_OK : PANEL_CARD_WRITE_FAILED;
    g_free(cards->write_message);
    cards->write_message = g_strdup(message != NULL ? message : "");
}

PanelCardWriteState panel_cards_write_state(PanelCards *cards)
{
    return cards != NULL ? cards->write_state : PANEL_CARD_WRITE_IDLE;
}

const gchar *panel_cards_write_message(PanelCards *cards)
{
    if (cards == NULL || cards->write_message == NULL)
        return "";
    return cards->write_message;
}
