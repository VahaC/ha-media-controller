#include "panel_config.h"

#include "json_helpers.h"

#include <glib/gstdio.h>

#define PANEL_CONFIG_CACHE_NAME "layout.json"

static gint clamp_kelvin(gdouble value, gint fallback)
{
    if (value < 1000.0 || value > 20000.0)
        return fallback;
    return (gint)(value + 0.5);
}

/* An unknown control name is ignored rather than treated as an error, so the
 * integration can add one without breaking a released panel. */
static void read_controls(JsonArray *controls, PanelRoom *room)
{
    room->brightness = FALSE;
    room->color_temperature = FALSE;
    if (controls == NULL)
        return;

    for (guint i = 0; i < json_array_get_length(controls); i++) {
        const gchar *control = json_array_get_string_element(controls, i);
        if (control == NULL)
            continue;
        if (g_str_equal(control, "brightness"))
            room->brightness = TRUE;
        else if (g_str_equal(control, "color_temp"))
            room->color_temperature = TRUE;
    }
}

static gboolean read_room(JsonObject *object, PanelRoom *room)
{
    const gchar *entity = json_object_string(object, "entity", NULL);
    if (entity == NULL || *entity == '\0')
        return FALSE;

    gdouble value = 0.0;
    room->slot = json_object_number(object, "slot", &value) && value > 0.0
                     ? (guint)value
                     : 0;
    room->entity = g_strdup(entity);
    room->label = g_strdup(json_object_string(object, "label", entity));
    read_controls(json_optional_array(object, "controls"), room);
    room->min_kelvin = json_object_number(object, "min_kelvin", &value)
                           ? clamp_kelvin(value, 2000)
                           : 2000;
    room->max_kelvin = json_object_number(object, "max_kelvin", &value)
                           ? clamp_kelvin(value, 6500)
                           : 6500;
    if (room->max_kelvin <= room->min_kelvin) {
        room->min_kelvin = 2000;
        room->max_kelvin = 6500;
    }
    return TRUE;
}

gboolean panel_config_parse_state(JsonObject *state, PanelLayout *layout,
                                  gchar **error_message)
{
    g_return_val_if_fail(layout != NULL, FALSE);
    g_return_val_if_fail(error_message != NULL, FALSE);

    JsonObject *attributes = json_state_attributes(state);
    if (attributes == NULL) {
        *error_message = g_strdup("The config sensor has no attributes.");
        return FALSE;
    }

    const gchar *player = json_object_string(attributes, "player", NULL);
    const gchar *queue = json_object_string(attributes, "queue", NULL);
    const gchar *playlists = json_object_string(attributes, "playlists", NULL);
    if (player == NULL || *player == '\0' || queue == NULL ||
        *queue == '\0' || playlists == NULL || *playlists == '\0') {
        *error_message = g_strdup(
            "The config sensor does not name the player, queue, and playlist "
            "entities yet.");
        return FALSE;
    }

    PanelLayout parsed = {0};
    parsed.player_entity = g_strdup(player);
    parsed.queue_entity = g_strdup(queue);
    parsed.playlists_entity = g_strdup(playlists);

    gdouble revision = 0.0;
    if (json_object_number(attributes, "revision", &revision))
        parsed.revision = (gint64)revision;

    JsonArray *slots = json_optional_array(attributes, "slots");
    guint length = slots != NULL ? json_array_get_length(slots) : 0;
    for (guint i = 0; i < length && parsed.room_count < PANEL_ROOM_MAX; i++) {
        JsonNode *node = json_array_get_element(slots, i);
        if (node == NULL || !JSON_NODE_HOLDS_OBJECT(node))
            continue;
        if (read_room(json_node_get_object(node),
                      &parsed.rooms[parsed.room_count])) {
            parsed.room_count++;
        }
    }

    panel_layout_clear(layout);
    *layout = parsed;
    return TRUE;
}

gboolean panel_config_parse_json(const gchar *data, gssize length,
                                 PanelLayout *layout, gchar **error_message)
{
    g_return_val_if_fail(error_message != NULL, FALSE);

    JsonParser *parser = json_parser_new();
    GError *error = NULL;

    if (!json_parser_load_from_data(parser, data, length, &error) ||
        !JSON_NODE_HOLDS_OBJECT(json_parser_get_root(parser))) {
        *error_message = error != NULL
                             ? g_strdup(error->message)
                             : g_strdup("The config sensor is not an object.");
        g_clear_error(&error);
        g_object_unref(parser);
        return FALSE;
    }

    gboolean parsed = panel_config_parse_state(
        json_node_get_object(json_parser_get_root(parser)), layout,
        error_message);
    g_object_unref(parser);
    return parsed;
}

gboolean panel_config_load_cache(PanelLayout *layout, gchar **error_message)
{
    gchar *path = app_config_cache_path(PANEL_CONFIG_CACHE_NAME);
    gchar *data = NULL;
    gsize length = 0;

    if (!g_file_get_contents(path, &data, &length, NULL)) {
        *error_message = g_strdup_printf(
            "Home Assistant is unreachable and no configuration has been "
            "cached yet.\n\nStart the panel once while Home Assistant "
            "answers at the URL in config.ini.");
        g_free(path);
        return FALSE;
    }
    g_free(path);

    gboolean parsed = panel_config_parse_json(data, (gssize)length, layout,
                                              error_message);
    g_free(data);
    return parsed;
}

void panel_config_store_cache(const gchar *data, gsize length)
{
    gchar *path = app_config_cache_path(PANEL_CONFIG_CACHE_NAME);
    GError *error = NULL;

    if (!g_file_set_contents(path, data, (gssize)length, &error)) {
        g_warning("Could not cache the panel configuration: %s",
                  error->message);
        g_clear_error(&error);
    } else {
        g_chmod(path, 0600);
    }
    g_free(path);
}
