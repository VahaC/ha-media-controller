#include "panel_grid.h"

#include "json_helpers.h"

#include <glib/gstdio.h>

#include <string.h>

#define PANEL_GRID_FILE_NAME "grid.json"

/* The default card. Two cells square is the smallest size that still holds a
 * name, a state and a full ADJUST button, so it is what a first run places. */
#define PANEL_GRID_DEFAULT_CARD 2

PanelGrid *panel_grid_new(guint columns, guint rows)
{
    PanelGrid *grid = g_new0(PanelGrid, 1);

    grid->columns = CLAMP(columns, (guint)PANEL_GRID_MIN_SIZE,
                          (guint)PANEL_GRID_MAX_SIZE);
    grid->rows = CLAMP(rows, (guint)PANEL_GRID_MIN_SIZE,
                       (guint)PANEL_GRID_MAX_SIZE);
    grid->cards = g_ptr_array_new_with_free_func(
        (GDestroyNotify)panel_card_free);
    return grid;
}

void panel_card_free(PanelCard *card)
{
    if (card == NULL)
        return;

    g_free(card->rid);
    g_free(card->icon);
    g_free(card->color);
    g_free(card);
}

void panel_grid_free(PanelGrid *grid)
{
    if (grid == NULL)
        return;

    g_ptr_array_unref(grid->cards);
    g_free(grid);
}

static gboolean cards_overlap(const PanelCard *a, const PanelCard *b)
{
    return a->x < b->x + b->width && b->x < a->x + a->width &&
           a->y < b->y + b->height && b->y < a->y + a->height;
}

gboolean panel_grid_can_place(const PanelGrid *grid, const PanelCard *card)
{
    if (grid == NULL || card == NULL)
        return FALSE;
    if (card->width == 0 || card->height == 0)
        return FALSE;
    /* Computed in this order so that a width large enough to wrap around is
     * still caught: both operands are bounded by the checks above. */
    if (card->x >= grid->columns || card->y >= grid->rows)
        return FALSE;
    if (card->width > grid->columns - card->x)
        return FALSE;
    if (card->height > grid->rows - card->y)
        return FALSE;

    for (guint i = 0; i < grid->cards->len; i++) {
        if (cards_overlap(g_ptr_array_index(grid->cards, i), card))
            return FALSE;
    }
    return TRUE;
}

/* A colour override is either a full `#rrggbb` or nothing. A half-written one
 * is dropped rather than repaired: the card then draws in the skin's own
 * colours, which is always a defensible picture. */
static gboolean color_is_usable(const gchar *color)
{
    if (color == NULL || strlen(color) != 7 || color[0] != '#')
        return FALSE;
    for (guint i = 1; i < 7; i++) {
        if (!g_ascii_isxdigit(color[i]))
            return FALSE;
    }
    return TRUE;
}

static gboolean read_cell(JsonObject *object, const gchar *member,
                          guint *value)
{
    gdouble number = 0.0;

    if (!json_object_number(object, member, &number))
        return FALSE;
    if (number < 0.0 || number > (gdouble)PANEL_GRID_MAX_SIZE)
        return FALSE;
    *value = (guint)number;
    return TRUE;
}

static PanelCard *read_card(JsonObject *object)
{
    const gchar *rid = json_object_string(object, "rid", NULL);
    guint x = 0;
    guint y = 0;
    guint width = 0;
    guint height = 0;

    if (rid == NULL || *rid == '\0')
        return NULL;
    if (!read_cell(object, "x", &x) || !read_cell(object, "y", &y))
        return NULL;
    if (!read_cell(object, "w", &width) || !read_cell(object, "h", &height))
        return NULL;

    PanelCard *card = g_new0(PanelCard, 1);
    card->x = x;
    card->y = y;
    card->width = width;
    card->height = height;
    card->rid = g_strdup(rid);

    const gchar *icon = json_object_string(object, "icon", NULL);
    if (icon != NULL && *icon != '\0')
        card->icon = g_strdup(icon);

    const gchar *color = json_object_string(object, "color", NULL);
    if (color_is_usable(color))
        card->color = g_ascii_strdown(color, -1);
    return card;
}

PanelGrid *panel_grid_parse(const gchar *data, gssize length, guint *dropped,
                            gchar **error_message)
{
    g_return_val_if_fail(error_message != NULL, NULL);

    if (dropped != NULL)
        *dropped = 0;
    if (data == NULL || (length == 0) || (length < 0 && *data == '\0')) {
        *error_message = g_strdup("The layout file is empty.");
        return NULL;
    }

    JsonParser *parser = json_parser_new();
    GError *error = NULL;

    /* A document of nothing but whitespace parses without error and leaves no
     * root at all, so the node is checked for existence before its type. */
    if (!json_parser_load_from_data(parser, data, length, &error) ||
        json_parser_get_root(parser) == NULL ||
        !JSON_NODE_HOLDS_OBJECT(json_parser_get_root(parser))) {
        *error_message = error != NULL
                             ? g_strdup(error->message)
                             : g_strdup("The layout is not an object.");
        g_clear_error(&error);
        g_object_unref(parser);
        return NULL;
    }

    JsonObject *root = json_node_get_object(json_parser_get_root(parser));
    gdouble version = 0.0;
    if (!json_object_number(root, "v", &version) ||
        (gint)version != PANEL_GRID_VERSION) {
        /* Refused rather than guessed at. Reading a format this build does
         * not know would move somebody's cards without telling them, and the
         * fallback — the default grid — is at least honest about it. */
        *error_message = g_strdup_printf(
            "The layout is version %d; this panel writes version %d.",
            (gint)version, PANEL_GRID_VERSION);
        g_object_unref(parser);
        return NULL;
    }

    guint columns = PANEL_GRID_COLUMNS;
    guint rows = PANEL_GRID_ROWS;
    gdouble number = 0.0;
    if (json_object_number(root, "cols", &number) && number >= 1.0)
        columns = (guint)MIN(number, (gdouble)PANEL_GRID_MAX_SIZE);
    if (json_object_number(root, "rows", &number) && number >= 1.0)
        rows = (guint)MIN(number, (gdouble)PANEL_GRID_MAX_SIZE);

    PanelGrid *grid = panel_grid_new(columns, rows);
    JsonArray *cards = json_optional_array(root, "cards");
    guint count = cards != NULL ? json_array_get_length(cards) : 0;
    guint lost = 0;

    for (guint i = 0; i < count; i++) {
        JsonNode *node = json_array_get_element(cards, i);
        if (node == NULL || !JSON_NODE_HOLDS_OBJECT(node)) {
            lost++;
            continue;
        }
        PanelCard *card = read_card(json_node_get_object(node));
        if (card == NULL) {
            lost++;
            continue;
        }
        /* A card that does not fit, or that lands on one already placed, is
         * dropped rather than moved. Where it should go instead is a question
         * only the person editing the grid can answer, and quietly relocating
         * it would hide the fact that the file was wrong. */
        if (!panel_grid_can_place(grid, card)) {
            panel_card_free(card);
            lost++;
            continue;
        }
        g_ptr_array_add(grid->cards, card);
    }

    g_object_unref(parser);
    if (dropped != NULL)
        *dropped = lost;
    return grid;
}

gchar *panel_grid_to_json(const PanelGrid *grid)
{
    g_return_val_if_fail(grid != NULL, NULL);

    JsonBuilder *builder = json_builder_new();

    json_builder_begin_object(builder);
    json_builder_set_member_name(builder, "v");
    json_builder_add_int_value(builder, PANEL_GRID_VERSION);
    json_builder_set_member_name(builder, "cols");
    json_builder_add_int_value(builder, grid->columns);
    json_builder_set_member_name(builder, "rows");
    json_builder_add_int_value(builder, grid->rows);
    json_builder_set_member_name(builder, "cards");
    json_builder_begin_array(builder);
    for (guint i = 0; i < grid->cards->len; i++) {
        const PanelCard *card = g_ptr_array_index(grid->cards, i);
        json_builder_begin_object(builder);
        json_builder_set_member_name(builder, "x");
        json_builder_add_int_value(builder, card->x);
        json_builder_set_member_name(builder, "y");
        json_builder_add_int_value(builder, card->y);
        json_builder_set_member_name(builder, "w");
        json_builder_add_int_value(builder, card->width);
        json_builder_set_member_name(builder, "h");
        json_builder_add_int_value(builder, card->height);
        json_builder_set_member_name(builder, "rid");
        json_builder_add_string_value(builder, card->rid);
        /* The card type is deliberately not written: it follows from the
         * domain of the registry element behind the rid, so storing it would
         * be a second copy of a fact that can change in Home Assistant. */
        if (card->icon != NULL) {
            json_builder_set_member_name(builder, "icon");
            json_builder_add_string_value(builder, card->icon);
        }
        if (card->color != NULL) {
            json_builder_set_member_name(builder, "color");
            json_builder_add_string_value(builder, card->color);
        }
        json_builder_end_object(builder);
    }
    json_builder_end_array(builder);
    json_builder_end_object(builder);

    gchar *json = json_builder_to_string(builder);
    g_object_unref(builder);
    return json;
}

PanelGrid *panel_grid_default(const PanelLayout *layout)
{
    PanelGrid *grid = panel_grid_new(PANEL_GRID_COLUMNS, PANEL_GRID_ROWS);
    guint count = layout != NULL && layout->entities != NULL
                      ? layout->entities->len
                      : 0;
    guint size = PANEL_GRID_DEFAULT_CARD;
    guint per_row = grid->columns / size;
    guint x = 0;
    guint y = 0;

    if (per_row == 0)
        return grid;

    for (guint i = 0; i < count; i++) {
        const PanelEntity *entity = g_ptr_array_index(layout->entities, i);
        if (y + size > grid->rows)
            break;

        PanelCard *card = g_new0(PanelCard, 1);
        card->x = x;
        card->y = y;
        card->width = size;
        card->height = size;
        card->rid = g_strdup(entity->rid);
        g_ptr_array_add(grid->cards, card);

        x += size;
        if (x + size > grid->columns) {
            x = 0;
            y += size;
        }
    }
    return grid;
}

gchar *panel_grid_path(void)
{
    gchar *directory = app_config_directory_path();
    gchar *path = g_build_filename(directory, PANEL_GRID_FILE_NAME, NULL);

    g_mkdir_with_parents(directory, 0700);
    g_free(directory);
    return path;
}

PanelGrid *panel_grid_load(const PanelLayout *layout)
{
    gchar *path = panel_grid_path();
    gchar *data = NULL;
    gsize length = 0;

    if (!g_file_get_contents(path, &data, &length, NULL)) {
        g_free(path);
        return panel_grid_default(layout);
    }
    g_free(path);

    gchar *failure = NULL;
    guint dropped = 0;
    PanelGrid *grid = panel_grid_parse(data, (gssize)length, &dropped,
                                       &failure);
    g_free(data);

    if (grid == NULL) {
        /* A broken file is not a reason to show an empty room page. The
         * default arrangement is drawn instead, and the file is left alone so
         * that whoever wrote it can still see what they wrote. */
        g_warning("Could not read the room layout (%s); using the default.",
                  failure);
        g_free(failure);
        return panel_grid_default(layout);
    }
    if (dropped > 0) {
        g_warning("Dropped %u unusable card(s) from the room layout.",
                  dropped);
    }
    return grid;
}

gboolean panel_grid_save(const PanelGrid *grid, gchar **error_message)
{
    g_return_val_if_fail(grid != NULL, FALSE);

    gchar *path = panel_grid_path();
    gchar *json = panel_grid_to_json(grid);
    GError *error = NULL;
    gboolean written = g_file_set_contents(path, json, -1, &error);

    if (!written) {
        if (error_message != NULL)
            *error_message = g_strdup(error->message);
        g_clear_error(&error);
    } else {
        g_chmod(path, 0600);
    }
    g_free(json);
    g_free(path);
    return written;
}
